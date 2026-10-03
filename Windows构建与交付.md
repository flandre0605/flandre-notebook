# Windows 构建与交付

更新：2026-10-03。本地交付版本 `0.2.0-preview.1`；尚未发布这个版本到 GitHub。

## 用户如何运行

- 安装版：运行 `FlandreNotebook-0.2.0-preview.1-setup-x64.exe`，使用中文安装向导，安装到当前用户目录；安装后从开始菜单打开。桌面快捷方式默认不勾选。
- 免安装版：完整解压 `FlandreNotebook-0.2.0-preview.1-portable-x64.zip`，运行 `FlandreNotebook/FlandreNotebook.exe`，保留旁边的 `_internal/`。无需另装 Python。
- 本次使用 Qt 6.11.2 构建，目标 Windows 10 1809 或更新版本、Windows 11 x64；实际运行验收在 Windows 11 进行，Windows 10 的范围来自 [Qt 支持平台](https://doc.qt.io/qt-6.11/supported-platforms.html)，尚未在 Windows 10 机器实测。
- 学习数据默认位于 `%LOCALAPPDATA%\FlandreNotebook\data`，与程序安装目录独立；卸载程序保留学习数据，换电脑使用 ZIP 备份/恢复。API Key 需重新录入。
- 旧源码版：先关闭并备份，再启动更新后的源码版一次，自动将旧项目 `data/` 迁入固定用户目录；也可在旧版导出 ZIP，安装新版后恢复。安装器不搜索磁盘上的其他源码目录。
- “免安装”指不用安装程序；默认仍使用固定用户数据目录。需要一套独立数据时，在启动前设置绝对路径 `FLANDRE_DATA_DIR`。指定此变量时不自动导入旧项目数据。

本轮安装器约 45.7 MiB，免安装 ZIP 约 62.9 MiB，完整程序目录约 143.2 MiB；题库、图片、备份和可选网页版服务的空间另计。ZIP 实际解压后已从项目外启动检查，文件摘要与应用源码摘要一致，包内不含个人题库、`.venv/`、截图文档或网页版环境。

## 开发者构建

构建只在 Windows 上执行。构建依赖和运行依赖分开管理；`requirements-build.txt` 固定本轮使用的主要组件版本，完整环境版本和应用源码摘要进入 `build-info.json`。

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-build.txt
.venv/Scripts/python.exe scripts/build_windows.py
```

生成免安装 ZIP 和 `dist/SHA256SUMS.txt`。同时生成安装包，需要 [Inno Setup](https://jrsoftware.org/isdl.php) 编译器：

```powershell
.venv/Scripts/python.exe scripts/build_windows.py --iscc "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"
```

本机编译器位于 `D:/project/build/tools/innosetup/ISCC.exe`，为官方签名的 6.7.3；该工具不进入 Git 或应用包。不要把这个机器路径写入运行代码。构建完成后可按 `SHA256SUMS.txt` 检查文件摘要。

## 文件职责与依赖边界

| 文件 | 职责 |
| --- | --- |
| `requirements.txt` | 应用运行依赖 |
| `requirements-build.txt` | 打包工具及本轮主要依赖版本 |
| `scripts/build_windows.py` | Windows 构建、使用说明/字体许可、版本清单、ZIP、安装器及 SHA256 |
| `packaging/flandre.spec` | PyInstaller 收集原生 Qt、图标、模板、公式字体及凭据后端 |
| `packaging/installer.iss` | 当前用户安装、中文向导、快捷方式及卸载；不操作学习数据目录 |
| `app/paths.py`、`services/storage.py` | 资源/用户目录分离与启动迁移 |
| `services/runtime_check.py` | 显式测试参数触发的实际运行验收；要求独立空工作区 |

程序使用目录形式打包，[PyInstaller](https://pyinstaller.org/en/stable/spec-files.html) 将解释器和运行库纳入包；只收集程序实际导入的 Qt 模块及必要原生库，不打包整个 `.venv/`、个人题库、截图文档或网页版反代。Qt 的底层库依赖由构建工具追踪，不手工删掉依赖 DLL。原生共享库保持独立文件，包内保留第三方组件说明、许可证、字体版权及来源。

构建进程的 `PATH` 限定为 Python 与 Windows 系统目录，并移除外部 `PYTHONPATH`。本次发现外部工具的 Poppler ICU 库遮蔽了 Windows ICU，同名但符号不兼容；不收紧环境会出现 QtGui 加载失败。构建成功不等于可运行，发布前必须执行实际 EXE 检查。

## 验收入口

```powershell
.venv/Scripts/python.exe checks/check_storage.py
.venv/Scripts/python.exe checks/check_model_selection.py
.venv/Scripts/python.exe checks/check_windows_package.py dist/FlandreNotebook/FlandreNotebook.exe
.venv/Scripts/python.exe checks/check_windows_installer.py dist/FlandreNotebook-0.2.0-preview.1-setup-x64.exe
```

- 目录迁移：临时题库验证首次复制、重复启动、旧 schema 升级、草稿与附件、缺图拒绝、复制失败、目标冲突及显式独立目录。旧数据原文件不改变。
- EXE：从项目外的临时目录启动，使用自己的资源；检查 Windows 凭据后端发现（不读写密钥）、公式、PDF、ZIP 恢复、选择题作答及 SAPI 插件。存在英语语音时实际静音合成 hello，检查 Speaking → Ready 和语速；不播放声音。
- 桌面模式：启动检查时可设置 `$env:QT_QPA_PLATFORM='windows'`。用临时 Ctrl+Alt+F23 注册真实全局热键，并向应用自己的窗口发送热键消息，确认回调，不截取用户桌面；原默认快捷键可能被其他软件占用，应用仍提供回退提示。正常检查缺省使用 offscreen。
- 安装器：拒绝覆盖已存在的同一应用安装。安装到临时目录，运行已安装 EXE，卸载后确认测试题库和图片仍在；等待 Inno 的第二阶段卸载进程释放文件后清理临时目录。
- `--verify-package <报告文件>` 是开发验收参数，只有提供 `FLANDRE_DATA_DIR` 时启用；使用单独的设置名称和空测试题库，不调用模型。

本轮 17 项源码检查（原 15 项、目录迁移与默认模型）通过。最终构建的实际 EXE 和安装器均已再次检查：Windows 11 桌面运行、默认模型设置与任务选择、固定尺寸单选图标、静音英语合成和语速、自定义全局热键回调、公式、PDF、ZIP 恢复与结构化选择题通过；卸载后测试题库与附件保留。后续每次重新构建都需重新执行检查。

## 真实模型验收与限制

已使用用户现有的 OpenAI 兼容配置 `tree / glm-5.3-flash` 对自制的两题图片做一次有效识图验收：返回两道独立题目、各自的 A/B 选项及正确答案 B，使用生产识题预设和解析校验。测试结果未写入个人题库；没有把密钥、账号或完整私人配置纳入文件。该结果证明这次简单样例能通过，不证明所有拍照、复杂公式或模型输出均正确，识题仍先核对草稿。

保存的真实响应随后在独立临时工作区经过生产界面的草稿编辑、两题确认、各自原图关联、选择 B 判分及 ZIP 备份恢复检查，未追加模型请求。模型英语解析中的时态说明经草稿编辑修正，说明核对环节仍有必要。

DeepSeek 网页版真实图片识别仍未验收，独立服务不包含在安装包中。当前程序、题库与模型能力的范围见开发手册；云同步、厂商原生接口及主观题语义判分属于后续设计。
