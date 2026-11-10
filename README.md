# The Harness

Automatic Control for bounded natural-language tasks. The model writes programs at decision
points; programs, policies and reactive rules act between decisions. Environment workers
check commands at their boundary. The controller Python process is separate from the target.

## Install from this source

Requires Python 3.11 or newer.

```bash
pip install -e .
harness install ./packages/computer ./packages/browser ./packages/workspace --link --yes
harness doctor
harness run "Inspect this project and summarize its structure" --folder . -p
```

Installing the core does not select external apps or agents. By default, Harness automatically installs the packages a requested task needs.
Configure a model before running a task; `harness` opens the optional persistent dialogue. Browser tasks need an installed
Chrome. Target-specific dependencies are installed in their own environments.

The optional `agent` package adds persistent identity and dialogue; core tasks and explicit
learning libraries do not require it. CLI, MCP and ACP entrypoints use the same core.

## Packages

<!-- generated: packages -->
| Package | What it is | Depends on | Provides |
|---|---|---|---|
| [acp](https://harness.lmms-lab.com/packages/acp/) | The Harness as an Agent Client Protocol agent for editors such as Zed | – | commands acp |
| [agent](https://harness.lmms-lab.com/packages/agent/) | Persistent identity, multi-turn dialogue and private memory over the Harness task engine | – | commands agent |
| [browser](https://harness.lmms-lab.com/packages/browser/) | Search and browse the web in a background browser | computer | skills browser; benches browser |
| [computer](https://harness.lmms-lab.com/packages/computer/) | Control a computer: its desktop, its applications in the background, displays of its own | – | embodiments computer, ubuntu; skills desktop, physical, screens; benches computer |
| [eval](https://harness.lmms-lab.com/packages/eval/) | Evaluate the agent: experiments over tasks and seeds, their suites, locks, run pages and self-improvement | local-models | commands config, inspect, lock, program, runs, self-improve, serve, view |
| [external-agents](https://harness.lmms-lab.com/packages/external-agents/) | ACP, terminal and cloud coding sessions, and bounded Claude Code and Codex delegates | – | commands agents |
| [local-models](https://harness.lmms-lab.com/packages/local-models/) | Models on your own GPUs: where services run (deploys), their weights and servers, Qwen3-VL | – | services qwen3-vl-32b, qwen3-vl-8b; commands down, fetch, services, status, up |
| [mcp-example](https://harness.lmms-lab.com/packages/mcp-example/) | An example MCP server: unit conversion | – | services mcp-units |
| [mcp-server](https://harness.lmms-lab.com/packages/mcp-server/) | The Harness as an MCP server (harness mcp), for apps, editors and agents that are MCP clients | – | commands mcp |
| [perception](https://harness.lmms-lab.com/packages/perception/) | See: segmentation, pointing, scenes, generic vision and vision-language models | local-models | skills pointing, scene, segmentation, vision, vlm; services molmo2, sam3, vision |
| [workspace](https://harness.lmms-lab.com/packages/workspace/) | Operate project files and processes in a bound working directory | – | embodiments workspace; skills workspace; benches workspace |
<!-- /generated: packages -->

## Development

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [the validation guide](docs/TESTING.md).
See [concepts](docs/src/content/docs/concepts/harness.mdx),
[CLI](docs/src/content/docs/use/cli.md) and [projects](docs/src/content/docs/use/projects.md).

## License and contributors

Public project code is MIT licensed; third-party material retains its own terms.
See [LICENSE](LICENSE) and [CONTRIBUTORS.md](CONTRIBUTORS.md).
