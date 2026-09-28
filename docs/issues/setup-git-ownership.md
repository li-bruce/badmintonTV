# Git工作树创建的账户所有权问题

状态：已解决（2026-09-28）。

现象：工作区由用户账户拥有，沙箱初始化的`.git`由沙箱账户拥有；应用创建worktree时Git报告dubious ownership。首次创建底座任务失败，未返回任务ID；后续已修复再创建，不属于重复任务。

解决：首次提交用指定路径的临时safe.directory；为了让Codex应用能调用Git，仅向当前用户Git配置添加 `safe.directory=C:/Users/USER/Desktop/Program/badmintonTV`。未设置通配符信任、未修改其他仓库。

验证：Git main正常、应用list_projects识别isGitRepository=true、四个worktree都指向 `a7b8e004378b2d9a6a27661cbcb136e74e6158db`。

后续若子任务沙箱账户遇到自己worktree的所有权检查，只按本任务已知路径局部处理，禁止设置`safe.directory=*`。
