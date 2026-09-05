# LungSight 本地推理服务

该服务把五折 ResNet18 研究模型改造成常驻本地 API。当前架构延续最初方案，运行权重则是
审计后重新训练的 `research-fivefold-20260902-165455`。模型权重在启动时完成 SHA-256 校验并只加载一次，
网页通过 `POST /api/analyze` 获取闭集内部排序。
分析任务、影像和医生复核记录保存在 `backend/data` 本地目录中。

账号、会话和OpenAI凭据也由后端管理。密码使用Argon2id哈希，浏览器仅持有
HttpOnly会话Cookie；OpenAI API Key使用Fernet加密后保存，接口只返回掩码。
新建CT任务按当前账号隔离，升级前产生的匿名历史任务不会自动显示给新账号。

每个新任务都会执行尺寸、亮度、对比度、边缘清晰度、SHA-256 重复和感知哈希近重复检查，
随后生成五折平均 Grad-CAM 注意力图并自动设置医生复核优先级。Grad-CAM 仅解释模型关注区域，
不等同于病灶定位或分割。

本地循证 Agent 从肺部 CT 研究材料、论文、模型程序和项目技术文档建立带文件哈希的
证据库。回答采用抽取式证据组合，每条结果保留来源、版本、页码或包内路径；证据不足或涉及
患者级诊疗时明确拒答。重新构建知识库可运行 `python build_knowledge.py`。

Agent 评测引擎使用 `evaluation_cases.json` 中的固定回归题集，检查回答状态、关键事实、
来源定位、无证据拒答和患者级诊疗拒答。评测运行记录保存在 SQLite，且不会写入病例循证历史。

当前支持与训练格式相近的二维图片及基础单帧 CT DICOM 序列导入。DICOM 在本机排序并转换为固定肺窗
派生 PNG，最多等距抽取 32 层；原始 DICOM 与身份字段值不落库，像素隐私仍需人工复核。
由于尚未完成患者级、病灶ROI、DICOM输入等价性和外部验证，所有图片序列与DICOM病例均强制拒绝
病例级候选，只保留内部工程排序。系统不支持诊断工作站能力或临床诊断。

## 启动

在 `backend` 目录创建 Python 3.11 环境并安装 `requirements.txt`，然后执行：

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8001
```

接口：

- `GET /api/health`
- `GET /api/model`
- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `PUT /api/auth/profile`：更新当前账号昵称（2至60字符）
- `POST /api/auth/avatar`：上传当前账号头像（multipart字段 `file`）
- `GET /api/auth/avatar`：读取当前登录账号的头像
- `POST /api/auth/logout`
- `GET /api/settings/openai`
- `PUT /api/settings/openai`
- `DELETE /api/settings/openai`
- `POST /api/settings/openai/test`
- `POST /api/analyze`
- `POST /api/analyze/series`
- `POST /api/analyze/dicom-series`
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/image`
- `GET /api/tasks/{task_id}/attention`
- `GET /api/tasks/{task_id}/audit`
- `GET /api/evidence/sources`
- `GET /api/evidence/sources/{source_id}/content`
- `GET /api/tasks/{task_id}/evidence/history`
- `POST /api/tasks/{task_id}/evidence/query`
- `GET /api/evaluation/dataset`
- `GET /api/evaluation/runs`
- `GET /api/evaluation/runs/{run_id}`
- `POST /api/evaluation/run`
- `POST /api/tasks/{task_id}/review`
- `GET /api/tasks/{task_id}/report`

除健康状态、模型信息和注册登录外，工作区接口均要求有效登录会话。
开发环境会在 `backend/data/credential_secret.key` 生成本地凭据加密密钥；正式部署时应通过
`LUNGSIGHT_CREDENTIAL_SECRET` 注入独立Fernet密钥，并通过HTTPS提供服务。

## 个人资料

账户面板中的头像和昵称可点击编辑，流程为确认更改、预览或编辑、保存。
修改仅影响当前登录账号，不改变邮箱、用户ID、会话和历史记录。

头像支持不超过3MB的PNG/JPEG/WebP静态图片，边长不超过4096像素、总像素不超过1600万。
后端验证实际图片格式后，按EXIF方向旋转并居中裁剪为256×256的PNG，同时去除元数据。
规范化的小型头像与账户资料一起存入本地SQLite，读取必须登录，响应禁止浏览器缓存。
更新昵称或头像会写入账户审计记录，不记录原始文件名或图像内容。

启动时自动执行增量迁移：新增 `users.avatar_version` 列和 `user_avatars` 表，不删除原有账号或凭据。
回归测试：在backend目录运行 `python -m unittest test_profile test_auth test_api_auth -v`，测试使用临时数据库，不访问真实模型API。

## 公开 DICOM 工程验证

`validate_public_dicom_e2e.py`可将一个已登记SHA-256的公开CT压缩包送入正式
`/api/analyze/dicom-series`接口，并使用真实五折模型验证DICOM读取、肺窗转换、Grad-CAM、
病例聚合、数据库留痕和报告生成。验证账号、派生切片和数据库全部位于临时目录，运行结束自动清除；
输出记录不包含DICOM身份字段值。该流程只验证工程闭环，不验证分类准确率，也不产生训练批准。

DICOM导入会先用双侧低密度肺野覆盖启发式确定连续有效区间，排除颈部、腹部等边缘低覆盖层，
再从有效区间等距抽取最多32层。筛选失败时保守回退完整序列并提示；该步骤不是肺分割、病灶定位
或医学有效性证明。

`validate_dicom_compatibility.py`用于批量建立多设备工程兼容性矩阵。它核对冻结压缩包哈希和对象数，
验证像素解码、排序、肺窗及肺野筛选，只输出设备与非识别性采集摘要；禁止输出研究对象编号及
Study/Series UID，不执行分类模型、不创建正式任务，也不改变正常标签或训练批准状态。

## 复核状态

新分析任务进入 `WAITING_FOR_REVIEW`。医生可以确认、修正或标记无法判断，任务随后分别进入
`CONFIRMED`、`CORRECTED` 或 `UNDETERMINED`。已完成复核的任务不可重复覆盖。

复核优先级分为 `ROUTINE`、`PRIORITY` 和 `HIGH_RISK`。它是工程排队规则，不是患者风险分层。
