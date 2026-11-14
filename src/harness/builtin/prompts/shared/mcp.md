
The tools of the MCP servers the user connected (the servers are listed at the end):

  mcp_tools()                       every tool: name, server, description, input_schema
  mcp_call(tool, **arguments)       call one; returns the whole MCP result: content,
                                    structuredContent, isError

- Read isError in the result before you go on.
- If a call fails with a transport error after it was sent, you do not know whether it
  took effect. Look at what it changed before anything else; do not send the same call
  again without looking.
- Images in a result's content are attached to your next observation by themselves.
  Print the text or structuredContent you need; do not print base64 image data.
- Calls to tools that share a resource run one after another.
