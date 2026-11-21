---
core: minor
---
One program waits behind a running one, not a chain. While a program of the model runs, the model is still told to write and send the next one with after(unit), and now to send that one only; once one waits behind the running program, it is told instead to send nothing more behind it, to look in on the running one and prepare, and to change or cancel the waiting one if what the running one left no longer fits it. after(unit) refuses a unit that itself still waits.
<!-- zh -->
运行中的程序后面只排一个，不排成一串。模型的程序在跑时，仍然让它用 after(unit) 写好并发出下一个程序，现在补了一句"只发这一个"；后面已经排了一个时，改成告诉它不要再往后接，去看正在跑的那个、做准备，并在正在跑的那个的结果不合适时改掉或取消排着的那个。after(unit) 拒绝去等一个自己还在排队的程序。
