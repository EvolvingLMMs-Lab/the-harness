<h1 align="center">
  <a href="https://harness.lmms-lab.com">
    <img alt="The Harness — by LMMs-Lab" src="docs/readme/header.svg" width="960">
  </a>
</h1>

<p align="center"><strong>Automatic Control for intelligence in action.</strong></p>

<p align="center">
  <a href="https://harness.lmms-lab.com/docs/getting-started/quickstart/">Quickstart</a> &nbsp; · &nbsp;
  <a href="https://harness.lmms-lab.com/docs/">Documentation</a> &nbsp; · &nbsp;
  <a href="https://harness.lmms-lab.com/docs/concepts/harness/">How it works</a>
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/@lmmslab/harness"><img alt="npm version" src="https://img.shields.io/npm/v/@lmmslab/harness?cacheSeconds=3600&amp;style=flat-square&amp;labelColor=112332&amp;color=087f9c" /></a>
  <a href="https://pypi.org/project/the-harness/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/the-harness?cacheSeconds=3600&amp;style=flat-square&amp;labelColor=112332&amp;color=087f9c" /></a>
  <a href="https://discord.gg/JbxU88aZyZ"><img alt="Discord community" src="https://img.shields.io/badge/discord-community-bc276e?style=flat-square&amp;logo=discord&amp;logoColor=white&amp;labelColor=112332" /></a>
</p>

Tell an agent what to do in your own words. A language model plans and writes short programs; The Harness runs them in an environment the agent can see and act in. Watch, send a message, or take over at any time.

The agent thinks while it acts: between model calls, its programs, skills and reactive rules keep working. What it learns along the way—notes, tested skills and rules—applies in the same run.

## Getting started

```bash
npm install -g @lmmslab/harness
harness
```

The Harness needs Python 3.11 or newer. You can also install it with `pip install the-harness`.

`harness` opens a conversation in your terminal. The first time, it asks which model to use and for its key; then type a task. Any model works: hosted ones through OpenRouter, OpenAI, Anthropic and other providers, or a model you run yourself.

See [Install](https://harness.lmms-lab.com/docs/getting-started/install/) and the [Quickstart](https://harness.lmms-lab.com/docs/getting-started/quickstart/) for a real task on your own computer.

## Commands

Use The Harness [in the terminal](https://harness.lmms-lab.com/docs/use/terminal/), run one task from [the CLI](https://harness.lmms-lab.com/docs/use/cli/), drive it from another program with JSON lines, call it from [apps, editors and other agents](https://harness.lmms-lab.com/docs/extend/editors/) over MCP and ACP, or build on the [Python API](https://harness.lmms-lab.com/docs/extend/python-api/).

```bash
harness                 # talk with the agent in the terminal
harness run "task" -p   # do one task and print the answer (--json: every event)
harness run rpc         # drive a conversation with JSON lines, from another program
harness install         # packages (also: list, remove)
harness library         # what the agent learned
harness replay          # a run again in the terminal
harness doctor          # what this computer has and lacks
```

## Where it works

pip/npm install only the small core. Environments come in packages, installed by
themselves the first time a task needs them.

| Environment | Package |
|---|---|
| Your computer: apps and windows, or a display of its own | `computer` |
| Websites, in a background browser | `browser` |
| Project files and processes, in a bound working directory | `workspace` |

## Packages

<!-- generated: packages -->
| Package | What it is | Depends on | Provides |
|---|---|---|---|
| [acp](https://harness.lmms-lab.com/packages/acp/) | The Harness as an Agent Client Protocol agent for editors such as Zed | – | commands acp |
| [agent](https://harness.lmms-lab.com/packages/agent/) | Persistent identity, multi-turn dialogue and private memory over the Harness task engine | – | commands agent |
| [browser](https://harness.lmms-lab.com/packages/browser/) | Search and browse the web in a background browser | computer | skills browser; benches browser |
| [computer](https://harness.lmms-lab.com/packages/computer/) | Control a computer: its desktop, its applications in the background, displays of its own | – | embodiments computer, ubuntu; skills desktop, physical, screens, windowtools; benches computer |
| [eval](https://harness.lmms-lab.com/packages/eval/) | Evaluate the agent: experiments over tasks and seeds, their suites, locks, run pages and self-improvement | local-models | commands config, inspect, lock, program, runs, self-improve, serve, view |
| [external-agents](https://harness.lmms-lab.com/packages/external-agents/) | ACP, terminal and cloud coding sessions, and bounded Claude Code and Codex delegates | – | commands agents |
| [local-models](https://harness.lmms-lab.com/packages/local-models/) | Models on your own GPUs: where services run (deploys), their weights and servers, Qwen3-VL | – | services qwen3-vl-32b, qwen3-vl-8b; commands down, fetch, services, status, up |
| [mcp-example](https://harness.lmms-lab.com/packages/mcp-example/) | An example MCP server: unit conversion | – | services mcp-units |
| [mcp-server](https://harness.lmms-lab.com/packages/mcp-server/) | The Harness as an MCP server (harness mcp), for apps, editors and agents that are MCP clients | – | commands mcp |
| [perception](https://harness.lmms-lab.com/packages/perception/) | See: segmentation, pointing, scenes, generic vision and vision-language models | local-models | skills pointing, scene, segmentation, vision, vlm; services molmo2, sam3, vision |
| [workspace](https://harness.lmms-lab.com/packages/workspace/) | Operate project files and processes in a bound working directory | – | embodiments workspace; skills workspace; benches workspace |
<!-- /generated: packages -->

## Documentation

- [Quickstart](https://harness.lmms-lab.com/docs/getting-started/quickstart/)
- [Automatic Control](https://harness.lmms-lab.com/docs/concepts/harness/): the ideas behind The Harness
- [Models and providers](https://harness.lmms-lab.com/docs/configure/models/)
- [Interrupt and take over](https://harness.lmms-lab.com/docs/use/interrupt/)
- [Let it learn an environment](https://harness.lmms-lab.com/docs/learn/learn-an-environment/)
- [Write a skill](https://harness.lmms-lab.com/docs/extend/skills/), [write a package](https://harness.lmms-lab.com/docs/extend/packages/), [add an environment](https://harness.lmms-lab.com/docs/extend/environments/)

## Development

```bash
pip install -e .
harness install ./packages/computer ./packages/browser ./packages/workspace --link --yes
harness doctor
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [the validation guide](docs/TESTING.md).

## Citation

```bibtex
@misc{lmmslab2026harness,
  author = {{LMMs-Lab}},
  title = {The Harness: Automatic Control for Intelligence in Action.},
  howpublished = {\url{https://github.com/EvolvingLMMs-Lab/the-harness}},
  year = {2026}
}
```

## License

MIT; third-party material retains its own terms. See [LICENSE](LICENSE) and
[CONTRIBUTORS.md](CONTRIBUTORS.md).
