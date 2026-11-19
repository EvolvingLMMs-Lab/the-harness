---
core: patch
---
A library entry admitted by its own test now has its text in the library's file. Such an admission recorded the new revision in the index, which is what loads, but left the file with the old text and removed the waiting copy, so anyone reading the file (a person, or a tool that copies the library) saw an entry other than the one in use. In one run a reactive tree changed and admitted by its own test was in the index while the file still held the tree from before.
<!-- zh -->
通过自身测试入库的库条目，现在会把文本写进库里的文件。以前这种入库只在索引里记下新版本（加载时用的是索引里的版本），文件却还是旧文本，候选区里等待的那份也被删掉了；所以读文件的人或者复制整个库的工具，看到的和实际在用的不是同一个条目。有一局里，反射树改过并通过自身测试入库，索引里是新树，文件里还是改之前的树。
