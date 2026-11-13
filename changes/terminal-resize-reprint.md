---
core: patch
---
On macOS and Linux, resizing the terminal no longer leaves rows of the input area behind: the terminal chat clears the screen and prints the conversation again at the new width, then draws the input area. Scrollback from before the chat started is cleared with it.
<!-- zh -->
在 macOS 和 Linux 上，调整终端窗口大小后不再残留输入区的旧行：终端对话会清屏，按新宽度重新输出整段对话，再画出输入区。聊天开始之前的终端滚动记录也会一并清除。
