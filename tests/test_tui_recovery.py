"""Offline regressions for session ownership, reading, and responsive host views."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import io
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import helpers  # noqa: F401
from prompt_toolkit.application import create_app_session
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.data_structures import Size
from rich.console import Console

from harness.core.lanes import Lanes
from harness.settings import ChoiceRequired
from harness.tui import editing, keymap, views
from harness.tui.chat import Chat, LOST
from harness.tui.history import History

HISTORY = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def chat(**fields):
    """A chat without its terminal: the state the chat keeps, and what it would print, note
    and do in the background kept in lists."""
    found = Chat.__new__(Chat)
    found.__dict__.update(conversation=None, status=None, before_start=None, generation=0,
        stop=threading.Event(), pending=[], starting=None, environment=None, agents_on=False,
        model_entry=None, model_effort=None, echoed=None, buffer=Buffer(multiline=True), ask=None,
        host=None, start=None, learning=None, armed={}, model=None, workspace=None,
        seen=[], answers=[], skills=[], printed=[], lanes=Lanes(), names={}, program=None, last_program=None,
        programs=0, said=None, keymap=keymap.Keymap(keymap.defaults()), attachments=editing.Attachments(),
        history=History(HISTORY.name, "here"), queue={"held": False, "running": None, "queued": []})
    found.console = Console(file=io.StringIO(), force_terminal=False, width=80)
    found.app = SimpleNamespace(output=DummyOutput(), invalidate=lambda: None, is_running=False, loop=None)
    found.notes, found.sent = [], []
    found.note = lambda text, *style: found.notes.append(str(text))
    found._print = lambda *lines: None
    found._background = lambda function, *args: found.sent.append((function, *args))
    found.__dict__.update(fields)
    return found


class SessionTests(unittest.TestCase):
    def test_start_completes_after_new_without_replacing_current_or_host(self):
        entered, release, ended = threading.Event(), threading.Event(), threading.Event()
        def start(*args, **kwargs):
            entered.set()
            release.wait(2)
            return object(), SimpleNamespace(name='old')
        found = chat(start=start)
        found._follow = Mock()
        def later(function, *args):
            function(*args)
            if function == found._started:
                ended.set()
        found._later = later
        found.send('old task')
        self.assertTrue(entered.wait(2))
        with patch('harness.providers.load', side_effect=ValueError('no model')):
            found._leave()
        release.set()
        self.assertTrue(ended.wait(2))
        found._follow.assert_not_called()
        self.assertIsNone(found.host)
        self.assertEqual(found.status, None)

    def test_failed_start_discards_queued_messages_before_next_start(self):
        entered, release, ended = threading.Event(), threading.Event(), threading.Event()
        def start(*args, **kwargs):
            entered.set()
            release.wait(2)
            raise RuntimeError('start failed')
        found = chat(start=start)
        found.note = lambda *args: ended.set()
        found.send('task')
        self.assertTrue(entered.wait(2))
        found.send('follow-up for failed task')
        release.set()
        self.assertTrue(ended.wait(2))
        found._follow = Mock()
        found._started(object())
        self.assertEqual(found.sent, [])
        self.assertEqual(found.pending, [])

    def test_a_failed_start_gives_the_message_back_to_the_input_box(self):
        found = chat(start=Mock(side_effect=RuntimeError('no key for the model')))
        found._later = lambda function, *args: function(*args)
        done = threading.Event()
        problem = found.problem
        found.problem = lambda *args: (problem(*args), done.set())
        found.send('do the thing')
        self.assertTrue(done.wait(2))
        self.assertEqual(found.buffer.text, 'do the thing')
        self.assertTrue(any('could not start' in note for note in found.notes))

    def test_shell_result_goes_to_origin_after_switch(self):
        entered, release, delivered = threading.Event(), threading.Event(), threading.Event()
        origin, other = object(), object()
        def run(*args, **kwargs):
            entered.set()
            release.wait(2)
            return SimpleNamespace(stdout='original output', stderr='', returncode=0)
        found = chat(conversation=origin)
        def background(function, *args):
            found.sent.append((function, *args))
            delivered.set()
        found._background = background
        with patch('harness.tui.chat.subprocess.run', side_effect=run):
            found._shell('slow', send=True)
            self.assertTrue(entered.wait(2))
            found.conversation, found.generation = other, 1
            release.set()
            self.assertTrue(delivered.wait(2))
        self.assertIs(found.sent[0][1], origin)

    def test_lost_host_invalidates_reference_and_resume_reconnects(self):
        old, replacement = object(), object()
        found = chat(host=old, status='RUNNING')
        found._lost(0, 'gone')
        self.assertIsNone(found.host)
        self.assertEqual(found.status, LOST)
        with patch('harness.host.Host.connect', return_value=replacement) as connect:
            self.assertIs(found._host(), replacement)
        connect.assert_called_once_with(start=True)

    def test_input_height_counts_soft_wrapped_wide_characters_and_status_fits(self):
        found = chat()
        found.app.output = Mock(get_size=Mock(return_value=Size(rows=24, columns=60)))
        found.buffer.text = '汉' * 100
        self.assertEqual(found._input_height(), 4)
        status = ''.join(text for _, text in found._status())
        hint = ''.join(text for _, text in found._hint())
        self.assertLessEqual(len(status) + len(hint), 60)


class ViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_paragraph_scrolls_to_tail_in_display_rows(self):
        real, apps = views.Application, []
        def application(*args, **kwargs):
            app = real(*args, **kwargs)
            apps.append(app)
            return app
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()), \
                patch.object(views, 'Application', side_effect=application):
            task = asyncio.create_task(views.read('Long', '汉' * 5000 + 'TAIL_SENTINEL'))
            await asyncio.sleep(.05)
            body = apps[0].layout.container.children[1]
            pipe.send_text('\x1b[6~' * 10)
            await asyncio.sleep(.05)
            content = body.content.create_content(80, 22)
            self.assertGreater(content.line_count, 100)
            self.assertEqual(content.cursor_position.y, content.line_count - 1)
            self.assertIn('TAIL_SENTINEL', ''.join(text for _, text in content.get_line(content.line_count - 1)))
            pipe.send_text('q')
            await asyncio.wait_for(task, 2)

    async def test_sessions_resume_and_host_transport_do_not_block_loop(self):
        for method in ('do_sessions', 'do_resume', 'do_status'):
            entered, release = threading.Event(), threading.Event()
            def wait(*args, **kwargs):
                entered.set()
                release.wait(2)
                return [] if method != 'do_status' else {}
            found = chat(host=SimpleNamespace(sessions=wait, info=wait, url='local'))
            tasks = []
            found.app.create_background_task = lambda coroutine: tasks.append(asyncio.create_task(coroutine))
            getattr(found, method)('')
            try:
                await asyncio.wait_for(asyncio.to_thread(entered.wait, 1), 2)
                await asyncio.sleep(.01)
                self.assertFalse(tasks[0].done())
            finally:
                release.set()
                await asyncio.wait_for(tasks[0], 2)

    async def test_host_exception_is_reported_by_command_boundary(self):
        found = chat(host=SimpleNamespace(info=Mock(side_effect=OSError('host gone')), url='local'))
        tasks = []
        found.app.create_background_task = lambda coroutine: tasks.append(asyncio.create_task(coroutine))
        with patch('harness.providers.reach', return_value={'ok': True, 'detail': None}):
            found.submit('/host')  # an alias of /status
            await tasks[0]
        self.assertTrue(any('host gone' in note for note in found.notes))
        self.assertIsNone(found.host)

    async def test_packages_route_reads_and_mutations_through_host_and_refresh_client(self):
        row = {'name': 'workspace', 'version': '1', 'enabled': True}
        host = Mock()
        host.get.side_effect = [{'packages': [row]}, {'shown': {'lines': ['workspace details']}}, {'packages': [row]}]
        host.post.return_value = {}
        async def work(title, function, **options):
            return await asyncio.to_thread(function, lambda line: None), None
        with patch.object(views, 'choose', side_effect=[1, 1, None]), \
                patch.object(views, 'working', side_effect=work), patch('harness.packages.activate') as activate:
            changed = await views.packages_view(host)
        host.post.assert_called_once_with('/api/app/packages/enable', {'name': 'workspace', 'on': False}, timeout=3600)
        self.assertEqual(activate.call_count, 2)
        self.assertEqual(changed, ['turn off workspace: done'])

    async def test_library_memory_loader_runs_outside_ui_thread(self):
        main = threading.get_ident()
        calls = []
        def memory():
            calls.append(threading.get_ident())
            return []
        async def load(title, function):
            return await asyncio.to_thread(function)
        with patch.object(views, '_load', side_effect=load), \
                patch('harness.runtime.learning.learner.libraries', return_value=[]), \
                patch.object(views, 'choose', side_effect=[0, None, None]):
            await views.library_view(memory)
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0], main)

    async def test_waiting_host_read_can_be_cancelled_without_applying_result(self):
        entered, release = threading.Event(), threading.Event()
        def wait():
            entered.set()
            release.wait(2)
            return 'late result'
        found = chat()
        applied = []
        async def read():
            applied.append(await found._request(wait))
        task = asyncio.create_task(found._guarded(read))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            self.assertIs(found.waiting, task)
            self.assertIn('esc to cancel', ''.join(text for _, text in found._hint()))
            task.cancel()
            await task
            self.assertEqual(applied, [])
            self.assertIsNone(found.waiting)
        finally:
            release.set()

    async def test_full_selected_option_is_keyboard_accessible(self):
        explanation = 'Environment explanation ' + 'very long ' * 50 + 'TAIL'
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()), \
                patch.object(views, 'read', new_callable=AsyncMock) as reader:
            task = asyncio.create_task(views.choose('Environment', ['short', explanation]))
            await asyncio.sleep(.03)
            pipe.send_text('Environment')
            await asyncio.sleep(.03)
            pipe.send_text('\x1bOQ')  # F2
            await asyncio.sleep(.03)
            reader.assert_awaited_once()
            self.assertEqual(reader.call_args.args[1], explanation)
            pipe.send_text('\r')
            self.assertEqual(await asyncio.wait_for(task, 2), 1)

    async def test_timeline_many_lanes_scroll_vertically(self):
        real, apps = views.Application, []
        def application(*args, **kwargs):
            app = real(*args, **kwargs)
            apps.append(app)
            return app
        lines = [('', '\n'.join(f'lane {n}' for n in range(100)))]
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()), \
                patch.object(views, 'Application', side_effect=application), \
                patch.object(views, 'timeline_lines', return_value=lines):
            task = asyncio.create_task(views.timeline_view(object()))
            await asyncio.sleep(.03)
            pipe.send_text('\x1b[6~' * 10)
            await asyncio.sleep(.03)
            body = apps[0].layout.container.children[1]
            content = body.content.create_content(80, 22)
            self.assertEqual(content.cursor_position.y, 99)
            self.assertGreater(body.vertical_scroll, 0)
            pipe.send_text('q')
            await asyncio.wait_for(task, 2)

    async def test_dismissible_working_view_keeps_loop_responsive(self):
        entered, release = threading.Event(), threading.Event()
        def wait(log):
            entered.set()
            release.wait(2)
            return 'late result'
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            task = asyncio.create_task(views.working('Reading', wait, cancellable=True))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                pipe.send_text('\x1b')
                result, error = await asyncio.wait_for(task, 2)
                self.assertIsNone(result)
                self.assertIsInstance(error, InterruptedError)
            finally:
                release.set()

    async def test_model_picker_remains_available_with_invalid_saved_default(self):
        found = chat(model_entry='missing')
        tasks = []
        found.app.create_background_task = lambda coroutine: tasks.append(asyncio.create_task(coroutine))
        row = dict(id='route', name='local', provider='openai', base_url='', enabled=True)
        async def view(coroutine):
            return await coroutine
        found._view = view
        with patch('harness.model_list.models', return_value=[row]), \
                patch('harness.model_list.select', side_effect=ValueError('configured model missing')), \
                patch.object(views, 'choose', return_value=0):
            found.do_model('')
            await tasks[0]
        self.assertEqual(found.model_entry, 'route')
        self.assertEqual(found.model, 'local')

    async def test_external_model_edit_preserves_removed_selection_and_refuses_default_fallback(self):
        found = chat(model_entry='removed', model_effort='high', start=Mock())
        tasks = []
        found.app.create_background_task = lambda coroutine: tasks.append(asyncio.create_task(coroutine))
        @asynccontextmanager
        async def terminal(*args, **kwargs):
            yield
        with patch('harness.model_list.models', return_value=[]), \
                patch('harness.tui.commands.data', return_value=Path('/temporary-test-path')), \
                patch('harness.tui.chat.in_terminal', terminal), \
                patch('harness.tui.chat.subprocess.run', return_value=SimpleNamespace(returncode=0)):
            tasks.append(asyncio.create_task(found._guarded(found._edit_models)))
            await tasks[0]
        self.assertEqual(found.model_entry, 'removed')
        self.assertIsNone(found.model_effort)
        self.assertIn('choose with /model', found.model)
        with patch('harness.model_list.select', side_effect=ValueError('explicit route was removed')) as select:
            found.send('must never reach the configured default')
        self.assertEqual(select.call_args.args[1], 'removed')
        found.start.assert_not_called()
        self.assertIsNone(found.status)
        self.assertEqual(found.model_entry, 'removed')
        self.assertTrue(any('Choose with /model' in line for line in found.notes))
        self.assertTrue(any('Save and close' in line and ':wq' in line for line in found.notes))

    async def test_abandoned_start_choice_never_opens_or_writes_settings(self):
        for per_conversation in (False, True):
            with self.subTest(per_conversation=per_conversation):
                entered, release = threading.Event(), threading.Event()
                choice = dict(title='Where?', section='session', key='environment',
                    per_conversation=per_conversation, options=[dict(label='None', name='None', value='none')])
                def start(*args, **kwargs):
                    entered.set()
                    release.wait(2)
                    raise ChoiceRequired(choice)
                found = chat(start=start, host=Mock())
                found.app.loop = asyncio.get_running_loop()
                old_threads = set(threading.enumerate())
                with patch.object(views, 'choose', return_value=1) as choose:
                    async def view(coroutine):
                        return await coroutine
                    found._view = view
                    found.send('old task')
                    self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                    worker = next(thread for thread in threading.enumerate()
                                  if thread not in old_threads and thread.name.startswith('Thread-'))
                    with patch('harness.providers.load', side_effect=ValueError('no model')):
                        found._leave()
                    release.set()
                    await asyncio.to_thread(worker.join, 1)
                    self.assertFalse(worker.is_alive())
                    choose.assert_not_awaited()
                    found.host.post.assert_not_called()
                    self.assertIsNone(found.conversation)

    async def test_session_read_abandoned_by_new_never_opens_picker_or_follows(self):
        entered, release = threading.Event(), threading.Event()
        def sessions():
            entered.set()
            release.wait(2)
            return [SimpleNamespace(row=dict(id='old', frontend='terminal', title='old', agents=[
                dict(id='main', depth=0, run='old', status='RUNNING')]))]
        found = chat(host=SimpleNamespace(sessions=sessions, conversation=Mock(return_value=object())))
        async def view(coroutine):
            return await coroutine
        found._view = view
        found._follow = Mock()
        tasks = []
        found.app.create_background_task = lambda coroutine: tasks.append(asyncio.create_task(coroutine))
        with patch.object(views, 'choose', return_value=0) as choose:
            found.do_sessions('')
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                with patch('harness.providers.load', side_effect=ValueError('no model')):
                    found._leave()
                release.set()
                await asyncio.wait_for(tasks[0], 2)
                choose.assert_not_awaited()
                found._follow.assert_not_called()
                self.assertIsNone(found.conversation)
            finally:
                release.set()

    async def test_stale_choice_coroutine_entry_does_not_open_modal(self):
        found = chat(generation=1, host=Mock())
        choice = dict(title='Where?', section='session', key='environment',
                      options=[dict(label='None', name='None', value='none')])
        with patch.object(views, 'choose') as choose:
            self.assertFalse(await found._choose_first_use(choice, generation=0))
            self.assertIsNone(await found._choose_environment(choice, generation=0))
        choose.assert_not_called()
        found.host.post.assert_not_called()

    async def test_first_use_choice_left_while_open_does_not_save_settings(self):
        found = chat(host=Mock())
        choice = dict(title='Where?', section='session', key='environment',
                      options=[dict(label='None', value='none')])
        async def view(coroutine):
            result = await coroutine
            with patch('harness.providers.load', side_effect=ValueError('no model')):
                found._leave()
            return result
        found._view = view
        with patch.object(views, 'choose', return_value=1):
            self.assertFalse(await found._choose_first_use(choice, generation=0))
        found.host.post.assert_not_called()

    async def test_shell_keeps_current_parked_conversation_resume_semantics(self):
        origin = SimpleNamespace(run='parked')
        found = chat(conversation=origin, status='FINISHED', parked=True)
        delivered = threading.Event()
        def background(function, *args):
            found.sent.append((function, *args))
            delivered.set()
        found._background = background
        with patch('harness.tui.chat.subprocess.run', return_value=SimpleNamespace(stdout='result', stderr='', returncode=0)):
            found._shell('echo result', send=True)
            self.assertTrue(await asyncio.to_thread(delivered.wait, 1))
        self.assertEqual(found.sent[0][0], found._continue)
        self.assertEqual(found.sent[0][1], 'parked')
        self.assertIn('result', found.sent[0][2])

    async def test_shell_current_finished_conversation_uses_normal_send_entrypoint(self):
        found = chat(conversation=object(), status='FINISHED')
        delivered = threading.Event()
        found.send = Mock(side_effect=lambda text: delivered.set())
        with patch('harness.tui.chat.subprocess.run', return_value=SimpleNamespace(stdout='result', stderr='', returncode=0)):
            found._shell('echo result', send=True)
            self.assertTrue(await asyncio.to_thread(delivered.wait, 1))
        found.send.assert_called_once()
        self.assertIn('result', found.send.call_args.args[0])
        self.assertEqual(found.sent, [])

    async def test_nested_option_reader_suspends_and_restores_parent_screen(self):
        class RecordingOutput(DummyOutput):
            def __init__(self):
                self.screens = []
            def enter_alternate_screen(self):
                self.screens.append('enter')
            def quit_alternate_screen(self):
                self.screens.append('exit')
        real, apps, output = views.Application, [], RecordingOutput()
        def application(*args, **kwargs):
            app = real(*args, **kwargs)
            apps.append(app)
            return app
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=output), \
                patch.object(views, 'Application', side_effect=application):
            task = asyncio.create_task(views.choose('Pick', ['alpha', 'target one', 'target two']))
            await asyncio.sleep(.03)
            pipe.send_text('target\x1b[B')
            await asyncio.sleep(.03)
            pipe.send_text('\x1bOQ')  # F2 opens the actual nested reader
            await asyncio.sleep(.03)
            self.assertEqual(len(apps), 2)
            self.assertTrue(apps[0]._running_in_terminal)
            self.assertEqual(output.screens, ['enter', 'exit', 'enter'])
            pipe.send_text('q')
            await asyncio.sleep(.03)
            self.assertFalse(apps[0]._running_in_terminal)
            self.assertEqual(apps[0].current_buffer.text, 'target')
            self.assertEqual(output.screens, ['enter', 'exit', 'enter', 'exit', 'enter'])
            pipe.send_text('\r')
            self.assertEqual(await asyncio.wait_for(task, 2), 2)
            self.assertEqual(output.screens[-1], 'exit')

    async def test_package_install_and_trust_retry_have_long_mutation_timeout(self):
        row = {'name': 'workspace', 'version': '1', 'enabled': True}
        host = Mock()
        host.get.side_effect = [{'packages': []}, {'results': [row]}, {'shown': {'lines': ['workspace']}}, {'results': [row]}]
        host.post.side_effect = [{'needs_trust': True, 'found': [row]}, {}]
        async def work(title, function, **options):
            self.assertFalse(options.get('cancellable', False) if title.startswith('Install') else False)
            return await asyncio.to_thread(function, lambda line: None), None
        with patch.object(views, 'choose', side_effect=[0, 1, 0, 1, 1, None]), \
                patch.object(views, 'working', side_effect=work), patch('harness.packages.activate'):
            changed = await views.packages_view(host)
        self.assertEqual(changed, ['install workspace: done'])
        self.assertEqual(host.post.call_args_list, [
            call('/api/app/packages/install', {'source': 'workspace'}, timeout=3600),
            call('/api/app/packages/install', {'source': 'workspace', 'trust': True}, timeout=3600)])

    async def test_banner_displays_model_recovery_warning_without_submitting_task(self):
        found = chat(start=SimpleNamespace(warning='Use /model or /models to repair the selected route.'))
        found._banner()
        self.assertTrue(found.notes, 'The model recovery warning must be visible')
        self.assertIn('Use /model or /models', found.notes[0])
        self.assertIsNone(found.conversation)
        self.assertEqual(found.sent, [])
        found.notes.clear()
        found.start = SimpleNamespace()
        found._banner()
        self.assertEqual(found.notes, [])

    async def test_cli_selected_model_seeds_status_and_effort_then_picker_resets_effort(self):
        starter = SimpleNamespace(model_entry='route-b', model_effort='high', model_name='Model B')
        app = SimpleNamespace(output=Mock(get_size=Mock(return_value=Size(rows=24, columns=100))))
        with patch.object(Chat, '_application', return_value=app), \
                patch('harness.providers.load', return_value={'model': 'Model A'}), \
                patch('harness.tui.chat.data', return_value=Path(HISTORY.name)):
            found = Chat(start=starter)
        self.assertEqual((found.model_entry, found.model_effort, found.model), ('route-b', 'high', 'Model B'))
        self.assertIn('Model B', ''.join(text for _, text in found._status()))
        found.note = Mock()
        tasks = []
        found.app.create_background_task = lambda coroutine: tasks.append(asyncio.create_task(coroutine))
        rows = [dict(id='route-b', enabled=True, name='Model B', efforts=['medium', 'high'], provider='openai', base_url=''),
                dict(id='route-c', enabled=True, name='Model C', efforts=['medium'], provider='openai', base_url='')]
        with patch('harness.model_list.select', return_value=rows[0]) as select:
            found.do_effort('medium')
            await tasks[-1]
        self.assertEqual(select.call_args.args[1], 'route-b')
        self.assertEqual((found.model_entry, found.model_effort), ('route-b', 'medium'))
        async def view(coroutine):
            return await coroutine
        found._view = view
        with patch('harness.model_list.models', return_value=rows), \
                patch('harness.model_list.select', return_value=rows[0]), patch.object(views, 'choose', return_value=1):
            found.do_model('')
            await tasks[-1]
        self.assertEqual((found.model_entry, found.model_effort, found.model), ('route-c', None, 'Model C'))

    async def test_mutation_wait_can_be_left_without_error_or_late_ui_updates(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def operation(log):
            entered.set()
            release.wait(2)
            log('late log must stay out of the closed view')
            finished.set()
            return {'installed': ['workspace']}
        real, apps = views.Application, []
        def application(*args, **kwargs):
            app = real(*args, **kwargs)
            app.exit = Mock(wraps=app.exit)
            apps.append(app)
            return app
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()), \
                patch.object(views, 'Application', side_effect=application):
            task = asyncio.create_task(views.working('Install workspace', operation, dismissible=True))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                title = apps[0].layout.container.children[0].content.create_content(100, 1)
                self.assertIn('Esc return; operation keeps running', ''.join(text for _, text in title.get_line(0)))
                pipe.send_text('\x1b')
                result, error = await asyncio.wait_for(task, 2)
                self.assertIs(result, views._DISMISSED)
                self.assertIsNone(error)
                self.assertFalse(finished.is_set())
                self.assertEqual(apps[0].exit.call_count, 1)
                release.set()
                self.assertTrue(await asyncio.to_thread(finished.wait, 1))
                await asyncio.sleep(.03)
                self.assertEqual(apps[0].exit.call_count, 1)
                logs = apps[0].layout.container.children[1].content.create_content(100, 10)
                self.assertNotIn('late log', ''.join(text for _, text in logs.get_line(0)))
            finally:
                release.set()

    async def test_dismissed_package_mutation_returns_outcome_guidance_without_retry(self):
        row = {'name': 'workspace', 'version': '1', 'enabled': True}
        host = Mock()
        host.get.side_effect = [{'packages': [row]}, {'shown': {'lines': ['workspace']}}]
        async def work(title, function, **options):
            if options.get('dismissible'):
                function(lambda line: None)
                return views._DISMISSED, None
            return await asyncio.to_thread(function, lambda line: None), None
        with patch.object(views, 'choose', side_effect=[1, 0]), \
                patch.object(views, 'working', side_effect=work), patch('harness.packages.activate') as activate, \
                patch.object(views, 'read') as read:
            changed = await views.packages_view(host)
        self.assertEqual(changed, ['Stopped waiting; check /packages for outcome'])
        host.post.assert_called_once_with('/api/app/packages/update', {'names': ['workspace']}, timeout=3600)
        self.assertEqual(activate.call_count, 1)  # refresh on entry; no late mutation callback
        read.assert_not_awaited()

    async def test_dismissed_trust_retry_returns_to_chat_without_failure(self):
        row = {'name': 'workspace', 'version': '1', 'enabled': True}
        host = Mock()
        host.get.side_effect = [{'packages': []}, {'results': [row]}, {'shown': {'lines': ['workspace']}}]
        host.post.side_effect = [{'needs_trust': True, 'found': [row]}, {}]
        mutations = []
        async def work(title, function, **options):
            value = await asyncio.to_thread(function, lambda line: None)
            if options.get('dismissible'):
                mutations.append(title)
                if len(mutations) == 2:
                    return views._DISMISSED, None
            return value, None
        with patch.object(views, 'choose', side_effect=[0, 1, 0, 1, 1]), \
                patch.object(views, 'working', side_effect=work), patch('harness.packages.activate'), \
                patch.object(views, 'read') as read:
            changed = await views.packages_view(host)
        self.assertEqual(changed, ['Stopped waiting; check /packages for outcome'])
        self.assertEqual(host.post.call_count, 2)
        read.assert_not_awaited()

    async def test_active_session_effort_ignores_invalid_new_conversation_default(self):
        class SelectionError(ValueError):
            pass
        for level, expected in [('high', 'high'), ('default', '')]:
            with self.subTest(level=level):
                conversation = Mock()
                found = chat(conversation=conversation, status='RUNNING')
                found._background = lambda function, *args: function(*args)
                tasks = []
                found.app.create_background_task = lambda coroutine: tasks.append(asyncio.create_task(coroutine))
                with patch('harness.model_list.select', side_effect=SelectionError('new-conversation default is invalid')) as select:
                    found.do_effort(level)
                    await tasks[-1]
                select.assert_not_called()
                conversation.set_model.assert_called_once_with(reasoning_effort=expected)

    async def test_active_session_effort_without_level_keeps_guidance_without_default_lookup(self):
        found = chat(conversation=Mock(), status='PAUSED')
        tasks = []
        found.app.create_background_task = lambda coroutine: tasks.append(asyncio.create_task(coroutine))
        with patch('harness.model_list.select', side_effect=ValueError('invalid unrelated default')) as select:
            found.do_effort('')
            await tasks[-1]
        select.assert_not_called()
        found.conversation.set_model.assert_not_called()
        self.assertIn('Use /effort LEVEL or /effort default', found.notes[-1])

    async def test_new_keeps_explicit_next_model_label_instead_of_configured_default(self):
        found = chat(conversation=SimpleNamespace(run='current'), status='IDLE',
                     model_entry='route-b', model_effort='medium', model='Active model A')
        found._open_environment = Mock()
        with patch('harness.model_list.select', return_value={'id': 'route-b', 'name': 'Model B'}) as select, \
                patch('harness.providers.load', return_value={'model': 'Hosted default'}) as load:
            found.submit('/new')  # an alias of /clear
        self.assertEqual((found.model_entry, found.model_effort, found.model), ('route-b', 'medium', 'Model B'))
        self.assertEqual(select.call_args.args[1], 'route-b')
        load.assert_not_called()
        self.assertIsNone(found.conversation)

    async def test_model_editor_refresh_does_not_replace_active_conversation_label(self):
        conversation = SimpleNamespace(run='active')
        found = chat(conversation=conversation, status='RUNNING', model='Active model', model_entry='removed', model_effort='high')
        self.assertFalse(found._refresh_next_model(rows=[]))
        self.assertEqual(found.model, 'Active model')
        self.assertEqual(found.model_entry, 'removed')
        self.assertIsNone(found.model_effort)
        self.assertIn('choose with /model', found.next_model_label)


if __name__ == '__main__':
    unittest.main()
