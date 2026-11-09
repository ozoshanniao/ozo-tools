# OZO Tools for Blender

Blender 骨架绑定与动画工作流工具集。一个插件，两个可独立折叠的面板：**OZO_Tools** 和 **RIG Tools**。

当前版本：**0.10.6** · 最低 Blender **5.2.0** · 已在 Blender **5.2.2 LTS** 测试 · GPL-3.0-or-later

## 下载与安装

1. 打开 [最新发布版本](https://github.com/ozoshanniao/ozo-tools/releases/latest)，下载 **OZO_Tools-0.10.6.zip**。
2. Blender → Edit → Preferences → Add-ons → 菜单 → **Install from Disk**，选择该 ZIP 并启用插件。
3. 在 3D View 按 **N**，打开 **OZO_Tools** 侧栏标签。

请选择 Release 附件中的插件 ZIP；GitHub 自动生成的 Source code ZIP 是整个源码仓库，不能直接作为插件安装包。

## 功能

| 面板 | 工具 | 用途 |
| --- | --- | --- |
| OZO_Tools | Copy Transform | 按骨骼名称前缀匹配并添加或修复 Copy Transforms 约束 |
| OZO_Tools | Deform | 按 DEF / ROOT 前缀统一骨骼 Deform 开关 |
| OZO_Tools | DEF Parenting | 保存原始层级、切到指定 Root、恢复原始层级 |
| OZO_Tools | Animation Scale | 处理骨架对象缩放及受支持动画数据的同步转换 |
| RIG Tools | Tweak / FK | 从选择的连续骨骼链创建 Tweak、Tip 和 FK 控制器 |
| RIG Tools | MCH Socket | 创建 Socket / INT 层级及位置、缩放、旋转约束 |
| RIG Tools | Rotation Follow | Direct 或 MCH 模式的旋转跟随、权重及总属性连接 |
| RIG Tools | Arm | 分阶段构建手臂 Switch、FK / IK、约束和 Pole |
| RIG Tools | Bone Identity | 检查和修复复制骨骼产生的重复身份编号 |

## 使用说明

- [完整英文说明与版本记录](OZO_Tools/README.md)
- [手臂绑定工作流](OZO_Tools/ARM_zh.md)
- [旋转跟随](OZO_Tools/ROTATION_FOLLOW_zh.md)
- [骨骼身份与重复编号修复](OZO_Tools/BONE_IDENTITY_zh.md)
- [动画缩放说明](OZO_Tools/ANIMATION_SCALE_zh.md)

各工具处理范围不同；请按对应说明选择骨架、骨骼和模式。绑定结构操作不自动补偿或烘焙已有动画，建议先在文件副本中验证。Animation Transfer 不包含在当前版本中。

## 源码、构建与测试

两个面板共享一个插件入口、版本、安装包和若干基础模块，因此在同一仓库维护。

```text
OZO_Tools/       插件源码、扩展清单和详细说明
dev/zip_build.py 构建 Blender 可安装 ZIP
dev/hot_reload.py 开发时热重载辅助工具
tests/          可独立运行的合成骨架回归测试
```

使用 Python 3.11+ 构建（无需安装 Blender Python 模块）：

```sh
python dev/zip_build.py
```

输出：`dist/OZO_Tools-0.10.6.zip`。依赖 Blender 自带的 bpy、mathutils 和 NumPy，无需外部服务或 API 密钥。

用 Blender 5.2 在独立后台进程运行测试；安装测试需要先构建 ZIP：

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/test_zip_install.py
python dev/run_tests.py --blender /path/to/blender
```

每个测试使用独立的出厂场景，不连接正在打开的 Blender。报告写入被 Git 忽略的 outputs/ 或 tests/*.json。测试目录不包含个人角色、场景文件或本地诊断数据。

## 许可证

[GNU GPL v3 或更新版本](LICENSE)。作者：OZO。