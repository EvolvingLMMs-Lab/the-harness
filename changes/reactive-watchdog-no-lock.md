---
core: patch
---
The watchdog that ends a reflex condition or controller at its deadline no longer stops the whole reflex tree. It raises the overrun in the caller's thread, where it lands at the next bytecode; when that was inside the watchdog's own bookkeeping, just after a lock was taken, the lock stayed held and every later reactive call waited on it for good (a run's reflexes all stopped and its programs hung behind a unit that never ended). The caller's side now takes no lock: arm and disarm are single dictionary operations, the watchdog is woken through a queue, and which side handles a due call is settled by removing it from the table.
<!-- zh -->
反射超时看门狗不会再让整棵反射树卡死。看门狗把"超时"异常抛进调用方的线程，这个异常会在该线程执行下一条字节码时落下；如果恰好落在看门狗自己的登记代码里、刚拿到锁之后，这把锁就永远不会释放，之后所有反射调用都卡在等这把锁上（有一局里所有反射全部停止，程序也都卡在一个永远不结束的单元后面）。现在调用方这边不再拿任何锁：登记和注销都是单次的字典操作，看门狗通过队列被唤醒，到期的调用由谁处理，靠"谁先把它从登记表里取走"来决定。
