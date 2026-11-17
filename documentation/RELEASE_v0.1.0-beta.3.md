# LungSight v0.1.0-beta.3

Windows 10/11 x64 公共测试版，2026-11-17。包含本地前后端运行时与通过清单校验的五折 ResNet18 研究权重。

## 本次更新

- 新版影像工作台：输入、查看和结果分区，示例缩略图、模型就绪状态与三步流程提示。
- 影像查看支持缩放、双击、Ctrl/Command + 滚轮、显示调节、Grad-CAM 叠加、人工标记和大图查看；原生全屏不可用时回退到窗口内大图。
- 后台分析任务可取消后继续，部分失败时保留成功项，服务重启后可恢复未完成工作。
- 统一分析、病例、病例库与设置页的视觉样式，提供亮色、夜间、护眼外观及窄屏布局。
- 人工标记、复核草稿与模型设置增加未保存保护；保存、模型检查和任务进度提供明确反馈。
- 保留按用户隔离的病例、问答、报告与模型服务设置。DeepSeek、ChatGPT 和 Kimi 需由使用者自行配置服务商 API Key；安装包不含预置凭据。
- 官网和软件首页同步新版下载、界面实图与当前模型说明；官网示例浏览不执行真实推理，也不生成模拟分析概率。

## 下载与安装

在本 Release 的 Assets 中下载 `LungSight-Setup-0.1.0-beta.3-win-x64.exe` 和 `SHA256SUMS.txt`。安装包约 668 MB，解包文件约 1.89 GB；支持 Windows 10/11 x64，按当前用户安装。

建议内存 8 GB 以上、预留至少 4 GB 磁盘空间。如果缺少兼容的 Microsoft VC++ x64 运行库，安装器会征求同意后从微软官网下载并打开其安装向导；这一步需要联网及管理员确认。

使用 PowerShell 核对校验值：

```powershell
Get-FileHash .\LungSight-Setup-0.1.0-beta.3-win-x64.exe -Algorithm SHA256
```

与 `SHA256SUMS.txt` 中对应行一致后，再运行安装程序。升级或卸载保留 `%LOCALAPPDATA%\LungSight` 下的用户数据。首次使用需注册本地账号；本地 CT 推理无需配置云端大模型。

## 验证范围与已知限制

- 前端 69 项测试、TypeScript 检查和生产构建通过；ESLint 无错误，保留原生图片元素提示。
- 包内 Python/Node 的 8 项工作流验收覆盖真实五折与 Grad-CAM、人工标记及报告、合成 DICOM、部分失败、取消与继续、缓存释放、后台重启恢复及未认证影像访问拒绝。
- 五折权重通过 SHA-256 校验，安装包执行完整性检查；公开包不含开发账号、数据库、用户影像、聊天记录或 API Key。
- 本轮验证直接运行包内服务，尚未覆盖完整 Windows 安装向导与桌面启动器操作。安装包未进行商业代码签名。
- 浏览器中原生全屏不可用时，使用已验证的窗口内大图。自动化未完成文件选择器与拖放上传验证，包内 API 的图片及合成 DICOM 导入已验证。
- 在线大模型联调沿用此前 DeepSeek 验收记录，本次界面与官网更新未重新调用在线模型。

## 研究用途边界

本版本仅供科研、教学、产品演示与流程验证，不是医疗器械，不用于独立诊断、病理确诊、分期、处方或治疗决策。Grad-CAM 为模型注意力图，不是病灶分割。

当前权重为 `research-fivefold-20260902-165455`。内部弱标签 OOF accuracy 为 84.98%、macro-F1 为 84.93%，不代表临床准确率。患者级独立性、外部多中心泛化、DICOM 输入等价性与病例级聚合尚未验证；病例级结论仍强制阻断。DINOv2 和 BiomedCLIP 未集成进安装包。

详细信息：

- [工作台界面与交互验收](https://github.com/wxy11117/LungSight/blob/main/documentation/UI_POLISH_2026-11-17.md)
- [后台任务与影像工作台更新](https://github.com/wxy11117/LungSight/blob/main/documentation/WORKBENCH_UPDATE_2026-11-17.md)
- [演示与使用步骤](https://github.com/wxy11117/LungSight/blob/main/documentation/COMPETITION_DEMO_GUIDE.md)
- [模型卡](https://github.com/wxy11117/LungSight/blob/main/documentation/MODEL_CARD_RESEARCH_2026-09-03.md)
