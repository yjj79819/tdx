# SOLO 自我进化经验手册

> 本文档记录 SOLO 在实际工作中积累的经验和技巧，避免重复犯错，提高自主完成能力。

---

## 一、Git 操作经验

### 1.1 Git 仓库同步问题

**问题**：本地 .git 目录丢失或损坏，无法推送

**解决方案**：
```bash
# 方案A：重新初始化并同步远程
git init
git remote add origin https://github.com/用户名/仓库名.git
git fetch origin main
git checkout -b main
git reset --hard FETCH_HEAD

# 方案B：强制同步远程
git fetch origin main
git reset --hard FETCH_HEAD
```

### 1.2 推送被拒绝问题

**问题**：`! [rejected] main -> main (non-fast-forward)`

**解决方案**：
```bash
# 先拉取再推送
git pull origin main --rebase
git push origin main

# 或者强制同步远程后重新提交
git fetch origin main
git reset --hard FETCH_HEAD
# 然后重新 add、commit、push
```

### 1.3 PowerShell 语法注意

**错误**：`&&` 在 PowerShell 中不是有效的语句分隔符

**正确做法**：
```powershell
# 错误
git add . && git commit -m "msg" && git push

# 正确（使用分号）
git add .; git commit -m "msg"; git push
```

---

## 二、GitHub Actions 工作流配置

### 2.1 定时任务频率限制

**限制**：
- 最短间隔：5 分钟（cron 支持分钟级）
- 实际延迟：可能有 1-5 分钟延迟
- 60 天无活动会自动禁用定时任务

### 2.2 最佳实践：分离高频和低频任务

**原则**：
- 股价更新：高频（开盘时段每5分钟）
- 排名/板块更新：低频（每小时或更低）

### 2.3 时区转换

**北京时间 = UTC + 8**

| 北京时间 | UTC时间 | Cron表达式 |
|----------|---------|------------|
| 9:00 | 1:00 | `0 1 * * 1-5` |
| 9:30 | 1:30 | `30 1 * * 1-5` |
| 15:00 | 7:00 | `0 7 * * 1-5` |

---

## 三、浏览器操作经验

### 3.1 可用的浏览器工具

- `browser_navigate` - 导航到URL
- `browser_click` - 点击元素
- `browser_scroll` - 滚动页面
- `browser_snapshot` - 获取页面快照
- `browser_wait_for` - 等待
- `browser_tabs` - 管理标签页
- `browser_unlock` - 解锁浏览器

### 3.2 操作流程

```
1. browser_navigate(url) → 导航
2. browser_snapshot() → 获取元素ref
3. browser_click(ref) → 点击
4. browser_unlock() → 解锁
```

---

## 四、GitHub Actions 手动触发

### 4.1 浏览器操作触发

**URL格式**：`https://github.com/用户名/仓库/actions/workflows/工作流文件名.yml`

**操作步骤**：
1. 导航到工作流页面
2. 点击 "Run workflow" 按钮
3. 确认触发

### 4.2 GitHub CLI 触发

```bash
# 检查是否安装
gh auth status

# 触发工作流
gh workflow run "工作流名称" --repo 用户名/仓库名
```

### 4.3 API 触发

需要 Personal Access Token：
```bash
curl -X POST \
  -H "Authorization: token YOUR_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/用户名/仓库/actions/workflows/工作流.yml/dispatches \
  -d '{"ref":"main"}'
```

---

## 五、自我进化原则

### 5.1 核心原则

1. **自己能做的事，不让用户代替**
2. **先尝试工具，失败再找替代方案**
3. **记录每次失败的原因和解决方案**

### 5.2 工具优先级

1. 直接工具调用（git、Write、Read等）
2. 浏览器操作（browser_*）
3. GitHub CLI (gh)
4. GitHub API (curl/Python)
5. 请求用户协助（最后手段）

### 5.3 已知限制

- 浏览器工具可能在某些情况下不可用
- GitHub CLI 可能未安装
- API触发需要 Personal Access Token

---

*本文档由 SOLO 自动维护，记录学习和进化过程。*
