"""Execution contracts across real stdio transport, host grants and resource owners."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import helpers
from harness.packages import Packages, MissingPackage
from harness.services.connectors import configured_servers
from harness.services.mcp import McpError, Resources, ToolAccess
from harness.services.mcp_stdio import StdioServer

SERVER = '''import json,sys
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 method=m['method']
 if method=='initialize': r={'protocolVersion':'2025-06-18','capabilities':{'tools':{}}}
 elif method=='tools/list': r={'tools':[{'name':'probe','inputSchema':{'type':'object'}}]}
 else:
  if m['params']['arguments'].get('exit'): sys.exit(3)
  r={'content':[{'type':'text','text':'receipt'},{'type':'image','mimeType':'image/png','data':'AA=='}],
     'structuredContent':{'value':7},'isError':bool(m['params']['arguments'].get('fail')),
     '_meta':{'source':'original'},'extra':'preserved'}
 print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':r}),flush=True)
'''


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.server = self.root/'server.py'
        self.server.write_text(SERVER)
        self.config = dict(command=sys.executable, args=[str(self.server)], allowed_tools=['probe'])

    def access(self, **kw):
        access = ToolAccess({'local':self.config}, directory=self.root, **kw)
        self.addCleanup(access.close)
        return access

    def test_stdio_preserves_all_content_and_native_errors(self):
        access = self.access()
        self.assertEqual(access.tools()[0]['name'], 'probe')
        for fail in (False, True):
            result = access.call('probe', {'fail':fail})
            self.assertEqual(result['structuredContent'], {'value':7})
            self.assertEqual(result['content'][1]['data'], 'AA==')
            self.assertEqual(result['isError'], fail)
            self.assertEqual(result['_meta'], {'source':'original'})
            self.assertEqual(result['extra'], 'preserved')

    def test_missing_grant_does_not_dispatch(self):
        self.config.pop('allowed_tools')
        access = self.access()
        self.assertEqual(access.tools(), [])
        with self.assertRaisesRegex(McpError, 'policy'):
            access.call('probe', {})

    def test_disabled_tool_overrides_wildcard_grant(self):
        self.config.update(allowed_tools=['*'],tools_off=['probe'])
        access = self.access()
        self.assertEqual(access.tools(), [])
        with self.assertRaises(McpError): access.call('probe', {})

    def test_stopped_caller_never_dispatches(self):
        called = Mock()
        with self.assertRaisesRegex(McpError, 'stopped before dispatch'):
            self.access().call('probe', {}, current=lambda:False, dispatched=called)
        called.assert_not_called()

    def test_server_exit_is_not_replayed(self):
        access = self.access()
        sent = Mock()
        with self.assertRaises(McpError):
            access.call('probe', {'exit':True}, dispatched=sent)
        sent.assert_called_once()
        self.assertEqual(access._clients['local'].process.wait(timeout=5), 3)

    def test_task_close_reaps_owned_transport(self):
        access = self.access()
        access.call('probe', {})
        process = access._clients['local'].process
        access.close()
        self.assertIsNotNone(process.poll())
        with self.assertRaisesRegex(McpError, 'closed'): access.tools()

    def test_shared_resource_waiter_stops_without_dispatch(self):
        resources = Resources()
        current = threading.Event(); current.set()
        started = threading.Event(); finished = threading.Event()
        errors = []
        def waiting():
            started.set()
            try:
                with resources.acquire('desktop', current.is_set):
                    errors.append('incorrect dispatch')
            except McpError:
                pass
            finally:
                finished.set()
        with resources.acquire('desktop', lambda:True):
            thread = threading.Thread(target=waiting)
            thread.start(); self.assertTrue(started.wait(2))
            # An independent resource advances while desktop is owned.
            with resources.acquire('other', lambda:True):
                current.clear()
            self.assertTrue(finished.wait(2))
        thread.join(2)
        self.assertEqual(errors, [])

    def test_entry_mcp_survives_cell_boundary_and_cancelled_waiter_does_not_act(self):
        import os, time
        from harness.host.tasks import TaskHost, TaskServer
        from harness.runtime.decision.model import ScriptedChat
        from harness import settings
        # Real host/kernel/stdio processes. The first call owns the resource;
        # cancellation of a sibling must not interrupt it or dispatch the sibling.
        self.server.write_text(SERVER.replace("r={'content'", "import time; time.sleep(0.5)\n  r={'content'"))
        code = """<python>
a = spawn(lambda: mcp_call('probe'), name='receipt')
b = spawn(lambda: mcp_call('probe', fail=True), name='cancelled')
b.cancel()
</python>"""
        chat = ScriptedChat([code, "<python>print(a.wait()); print(b.status)</python>",
                             "<finish>done</finish>"])
        with patch.dict(os.environ, {settings.KEY:'test-no-network', 'HARNESS_HOME':str(self.root/'home')}), \
                patch('harness_workspace.host.environment_python', return_value=sys.executable):
            (self.root/'home/libraries/project').mkdir(parents=True)
            app = TaskHost(self.root/'host', chat=chat, verifier=ScriptedChat([]))
            app.settings.update({'learning':{'mode':'frozen'}, 'limits':{'agent_depth':0}})
            app.settings.put('connectors',[dict(id='local',transport='stdio',**self.config)])
            server = TaskServer(('127.0.0.1',0), app, token='test')
            try:
                (self.root/'project').mkdir()
                run=app.start(server,'Read a tool receipt',folder=str(self.root/'project'))
                task=server.conversations[run]
                deadline=time.monotonic()+30
                while task.status not in ('FINISHED','ERROR') and time.monotonic()<deadline:
                    time.sleep(.05)
                records=[json.loads(line) for line in (task.directory/'events.jsonl').read_text().splitlines()]
                self.assertEqual(task.status,'FINISHED',str(records[-8:])+ '\n' + '\n'.join(p.read_text(errors='replace') for p in (self.root/'host/logs/targets').glob('*.log')))
                dispatched=[r for r in records if r['event']=='mcp_dispatched']
                receipts=[r for r in records if r['event']=='mcp_receipt' and r.get('dispatched')]
                self.assertEqual(len(dispatched),1, str(dispatched))
                self.assertEqual(len(receipts),1)
                self.assertFalse(receipts[0]['late'], str(receipts))
                self.assertEqual(receipts[0]['outcome'],'returned')
                self.assertTrue(any(r['event']=='entry_end' and r.get('status')=='cancelled' for r in records))
            finally:
                for task in server.conversations.values(): task.close()
                for thread in list(app._threads.values()): thread.join(15)
                app.close(); server.server_close()

    def live_access(self):
        from harness.host.tasks import TaskHost
        host = TaskHost(self.root / 'live-home')
        self.addCleanup(host.close)
        record = dict(id='local', transport='stdio', **self.config)
        host.settings.put('connectors', [record])
        access = ToolAccess(host.mcp_servers(), directory=self.root, authorize=host.authorize_mcp)
        self.addCleanup(access.close)
        return host, record, access

    def test_live_revocations_and_binding_changes_reject_existing_client(self):
        host, record, access = self.live_access()
        self.assertEqual(access.call('probe', {})['structuredContent'], {'value':7})
        process = access._clients['local'].process
        changes = [[], [{**record, 'enabled':False}], [{**record, 'tools_off':['probe']}],
                   [{**record, 'allowed_tools':[]}], [{**record, 'args':[str(self.server),'changed']}],
                   [{**record, 'env':{'TOKEN':'rotated'}}]]
        for changed in changes:
            with self.subTest(change=changed):
                host.settings.put('connectors', changed)
                dispatched = Mock()
                with self.assertRaises(McpError): access.call('probe', {}, dispatched=dispatched)
                dispatched.assert_not_called()
                self.assertEqual(access.tools(), [])
                host.settings.put('connectors', [record])
                self.assertEqual(access.call('probe', {})['structuredContent'], {'value':7})
                self.assertIs(access._clients['local'].process, process)

    def test_stored_credential_rotation_rejects_old_client(self):
        from harness.host.tasks import TaskHost
        host = TaskHost(self.root / 'credential-home')
        self.addCleanup(host.close)
        host.credentials.keep('HARNESS_MCP_LOCAL_TOKEN', 'first-test-value')
        record = dict(id='local', transport='stdio', env={'TOKEN':'{TOKEN}'},
                      secrets=['TOKEN'], **self.config)
        host.settings.put('connectors', [record])
        access = ToolAccess(host.mcp_servers(), directory=self.root, authorize=host.authorize_mcp)
        self.addCleanup(access.close)
        access.call('probe', {})
        host.credentials.keep('HARNESS_MCP_LOCAL_TOKEN', 'second-test-value')
        dispatched = Mock()
        with self.assertRaises(McpError): access.call('probe', {}, dispatched=dispatched)
        dispatched.assert_not_called()

    def test_queued_call_rechecks_permission_after_resource_wait(self):
        host, record, access = self.live_access()
        access.call('probe', {})
        acquire = access.resources.acquire
        waiting = threading.Event()
        def tracked(*args):
            waiting.set()
            return acquire(*args)
        dispatched, errors = Mock(), []
        def call():
            try: access.call('probe', {}, dispatched=dispatched)
            except McpError as error: errors.append(str(error))
        with acquire('local', lambda:True):
            with patch.object(access.resources, 'acquire', side_effect=tracked):
                thread = threading.Thread(target=call)
                thread.start()
                self.assertTrue(waiting.wait(5))
                host.settings.put('connectors', [{**record, 'tools_off':['probe']}])
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        dispatched.assert_not_called()

    def test_live_grant_does_not_expand_original_task_authority(self):
        self.config['allowed_tools'] = []
        host, record, access = self.live_access()
        self.assertEqual(access.tools(), [])
        host.settings.put('connectors', [{**record, 'allowed_tools':['probe']}])
        with self.assertRaises(McpError): access.call('probe', {})

    def test_task_rechecks_live_grants_between_programs(self):
        import os, time
        from harness.host.tasks import TaskHost, TaskServer
        from harness.runtime.decision.model import ScriptedChat
        from harness import settings
        chat = ScriptedChat(["<python>print(mcp_call('probe'))</python>",
            "<python>\ntry: mcp_call('probe')\nexcept Exception: print('REVOKED')\n</python>",
            "<finish>done</finish>"])
        with patch.dict(os.environ, {settings.KEY:'test-no-network', 'HARNESS_HOME':str(self.root/'home')}), \
                patch('harness_workspace.host.environment_python', return_value=sys.executable):
            (self.root/'home/libraries/project').mkdir(parents=True)
            app = TaskHost(self.root/'host', chat=chat, verifier=ScriptedChat([]))
            app.settings.update({'learning':{'mode':'frozen'},'limits':{'agent_depth':0},
                                 'model':{'think_while_acting':'off'}})
            record = dict(id='local', transport='stdio', **self.config)
            app.settings.put('connectors', [record])
            complete = chat.complete
            def reply(*args, **kwargs):
                if chat.calls == 1:
                    app.settings.put('connectors', [{**record, 'enabled':False}])
                return complete(*args, **kwargs)
            server = TaskServer(('127.0.0.1',0), app, token='test')
            try:
                (self.root/'project').mkdir()
                with patch.object(chat, 'complete', side_effect=reply):
                    run = app.start(server, 'Observe permission changes', folder=str(self.root/'project'))
                    task = server.conversations[run]
                    deadline = time.monotonic()+30
                    while task.status not in ('FINISHED','ERROR') and time.monotonic()<deadline:
                        time.sleep(.05)
                records = [json.loads(line) for line in (task.directory/'events.jsonl').read_text().splitlines()]
                self.assertEqual(task.status, 'FINISHED', str(records[-5:]))
                self.assertEqual(sum(r['event']=='mcp_dispatched' for r in records), 1)
                denied = [r for r in records if r['event']=='mcp_receipt' and r['outcome']=='not_dispatched']
                self.assertEqual(len(denied), 1)
                self.assertTrue(any(r['event']=='cell' and 'REVOKED' in r['result'].get('stdout','') for r in records))
            finally:
                for task in server.conversations.values(): task.close()
                for thread in list(app._threads.values()): thread.join(15)
                app.close(); server.server_close()

    def test_configuration_resolves_without_ui_and_keeps_explicit_grants(self):
        credentials = Mock()
        credentials.secret.return_value = 'private'
        record = dict(id='tools',transport='stdio',command=sys.executable,args=['{FILE}'],
                      fields={'FILE':str(self.server)},env={'TOKEN':'{TOKEN}'},secrets=['TOKEN'],
                      allowed_tools=['probe'],resource='desktop')
        result = configured_servers({'connectors':[record]},credentials)['tools']
        self.assertEqual(result['args'],[str(self.server)])
        self.assertEqual(result['env'],{'TOKEN':'private'})
        self.assertEqual(result['allowed_tools'],['probe'])
        self.assertEqual(result['resource'],'desktop')

    def test_explicit_off_never_queries_registry_or_installs(self):
        with patch.dict('os.environ',{'HARNESS_AUTO_INSTALL':'off'}):
            registry = Mock()
            manager = Packages(self.root/'data',cwd=self.root,registry=registry)
            with patch.object(manager,'install') as install, patch.object(manager,'provider',return_value=None):
                with self.assertRaises(MissingPackage): manager.ensure('commands','agent')
            install.assert_not_called()
            registry.providers.assert_not_called()

    def test_selected_catalog_installs_its_required_provider(self):
        from harness.host.tasks import TaskHost
        host = TaskHost.__new__(TaskHost)
        host.settings = Mock()
        host.settings.get.return_value = {'connectors':[{'id':'selected','catalog':'fetch'}]}
        host.credentials = Mock(); host.packages = Mock()
        provider = Mock()
        provider.mcp_servers.return_value = {'selected':{'url':'http://localhost/mcp'}}
        with patch('harness.extensions.hosts', side_effect=[[], [('provider',provider)]]), \
                patch('harness.packages.activate'):
            self.assertEqual(host.mcp_servers(), provider.mcp_servers.return_value)
        host.packages.ensure.assert_called_once_with('commands','app')

    def test_host_configuration_never_installs_app(self):
        from harness.host.tasks import TaskHost
        host = TaskHost.__new__(TaskHost)
        host.settings = Mock()
        host.settings.get.return_value = {'connectors':[dict(id='tools',transport='stdio',
            command=sys.executable,args=[str(self.server)],allowed_tools=['probe'])]}
        host.credentials = Mock(); host.packages = Mock()
        with patch('harness.extensions.hosts',return_value=[]):
            self.assertEqual(host.mcp_servers()['tools']['command'], sys.executable)
        host.packages.ensure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
