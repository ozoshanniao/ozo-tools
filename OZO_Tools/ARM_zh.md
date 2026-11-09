# OZO_Tools · Arm 分步绑定（0.10.5）

入口：3D View → N 侧栏 → **OZO_Tools → RIG Tools → Arm**。与 Tweak / FK、MCH Socket、Rotation Follow 为同级分区；每步可折叠。Blender 5.2+；活动、本地、可编辑、单用户骨架；支持 Edit/Pose Mode。

## 准备与映射

入口为已经创建、调整好主 Tweak 的手臂，不需要通用 Create FK。每个实例处理 Arm、Forearm、Hand 三根主 ORG、各自主 Tweak 和一个已有 Hand Tip Tweak。肩膀、手指、细分链、次级 Tweak、Twist 不自动加入。

- 选中 OZO 原有三骨 Tweak 链的任意成员，点 **Load Tweak Mapping**；读取原记录的身份和顺序，不按名称猜角色。填写后核对角色。
- 或手工填写 **Role Mapping** 七项：Arm ORG/Tweak、Forearm ORG/Tweak、Hand ORG/Tweak、Hand Tip Tweak。允许 Forarm 等任意拼写，Tip 名称明确选择。
- 插入 Tweak 后，ORG 不必直接互为父子；角色顺序来自映射。
- **New Arm Mapping** 清空当前映射与活动实例，保留已建实例。另一侧从第一步开始。同一骨架可存多个实例。
- **Arm Instance → Load** 恢复该实例映射和已应用的 IK 参数；**Check** 同步编辑模式数据并检查完整性。骨骼合理改名后靠稳定身份识别；删除后同名重建不是原骨。

后续按钮以活动实例和映射为准，不受之后的骨骼选择变化影响。改变映射后应创建新 Switch 或加载对应实例，否则后续操作报告映射不一致。

## 1. Create Switch Chain

从三个 ORG 的静止几何生成 MCH_Switch_<基础名>.L/.R，保持位置、长度、朝向和 Roll。清理 ORG_ / ORG-、末尾 .001 等副本编号，保留 _01 等有意义编号与 .L/.R。支持无侧后缀；三段来源须有相同侧后缀或全部无后缀。命名冲突明确报告。

- Switch Root Parent 默认读取执行前 Arm Tweak 的父级，也可 Specify Bone 或 None。
- Switch 为 Arm → Forearm → Hand；Connected 全部关闭。
- 三个主 Tweak 分别成为对应 Switch 的 Keep Offset 子级。
- Hand Tip Tweak 直接挂在 Switch Hand 下，不挂 Hand Tweak。
- ORG 静止几何、已有 Tweak 关系、约束、动画和驱动保留。Tweak/Tip 原父级与 Connected 被记录。
- 此步不接 FK/IK 输入，不位移原 ORG。

所有生成骨 Deform 关闭；不复制来源约束、动画、驱动、姿态或自定义属性，只写自己的身份标记。**Specify Collection** 开启时选择已有集合（包括嵌套），关闭时使用点击当时的活动集合；不自动创建集合。

## 2. Create FK / IK Chains

只复制已记录的三根 Switch 的当前静止几何，不复制 Tweak、ORG 或 Tip 后代。

- FK 名称为 Arm_FK.L、Forearm_FK.L、Hand_FK.L 形式；保留实际来源拼写。
- IK 名称为 MCH_IK_Arm.L、MCH_IK_Forearm.L、MCH_IK_Hand.L 形式。0.10.5 按用户修正确认：MCH_IK_Hand 无父级，作为独立手部目标机制骨。
- 两条根使用执行第二步时 Switch 根的当前父级。可以先手工改父级或插入 Socket；不拿第一步旧父级覆盖。
- FK 全部 Keep Offset；IK Forearm 与 Arm Connected；IK Hand 无父级、Connected 关闭。第四步由 Copy Transforms 跟随 Hand IK 控制器，不依赖父级跟随。
- Switch Arm 尾与 Forearm 头不重合时拒绝，不偷偷移动来源来连接。
- FK/IK 分别选择集合；此步不接 Switch 约束。

## 3. Create IK Controls

- Hand IK 为 <Hand基础名>_IK.L/.R，复制 IK Hand 的静止几何。
- Pole 为 <Arm基础名>_IK_POLE.L/.R，默认 **Pole Position → Upper Arm Local X**：读取 IK 大臂完整静止几何，从大臂尾端沿该骨局部 +X 偏移。数学上等价于复制大臂、沿局部 X 平移、取副本尾端作为 Pole 头；不创建额外定位骨，也不使用缩短的 Tweak 或当前 IK 姿态。
- **Distance** 是骨架空间距离。0 表示创建/显式更新时的大臂长度；具体正值可指定距离；**Flip Direction** 反向。
- Pole 从定位点沿世界 **+Y** 延伸，Roll 按世界 **+Z** 参考重新计算，考虑骨架对象变换。**Pole Length** 为骨架空间长度。
- 两个控制骨初始父级为 **Root**。空值仅在唯一大小写不敏感 ROOT/root/Root 存在时自动查找，否则明确选择。
- **Create Pole Visual** 默认开启，创建 VIS_<Arm基础名>_POLE.L/.R，从肘指向 Pole。可在创建前关闭；不会反向影响 IK。
- **Rest Bend** 保留旧版肩腕投影定位方式；**Explicit Direction** 可填写非零且不平行肩腕线的骨架空间方向。近直链没有唯一几何弯曲平面，但 Upper Arm Local X 可由已存在的大臂骨轴确定位置；这不代表直链有可供 Match Rest Bend 校准的弯曲参考。
- 本步有控制骨集合设置，不立即创建 IK 约束。

可在 Edit Mode 手调控制骨，保存后继续。**Update Pole Placement / Length** 按所选定位模式重设 Pole 位置、长度，同时恢复世界 +Y 轴向及 +Z Roll；不重置 Hand IK，不增删可视杆。仅修改面板参数不自动改骨骼，再次 Create 或 Load 不覆盖用户几何。

### 修正已做到第三步或第四步的旧实例

安装 0.10.4 后在 Arm Instance 选择原实例并点 Load，展开第三步，点 **Align Pole: Upper Arm X**。这会明确切换到局部 X 定位，并原地更新 Pole 头、尾和 Roll，保留原骨身份、父级、集合、约束、驱动及其他步骤记录。Distance/Flip/Pole Length 仍按当前设置应用。旧实例不会因打开文件、Load 或再次 Create 而自动搬动 Pole。

如果第四步已连接 IK，再点 **Match Rest Bend**；若还没连接，先 Connect IK 再 Match Rest Bend。任意三维静止几何/骨 Roll 下，准确沿局部 X 定位不等于 Pole Angle 必然为 0，仍需该校准消除剩余求值偏差。显示杆在已连接时自动跟随修正后的 Pole。整个明确修正支持 Undo/Redo 和失败回滚。

## 4. Connect IK

先明确选择 **Elbow Bend Axis**（局部 X/Y/Z）；仅在 Forearm 上解锁该轴、锁定另外两个 IK 轴。大臂作为肩部关节，XYZ 三个 IK 旋转轴全部解锁，不能套用小臂的单轴限制。不根据左右名称猜轴。Pole 定位方向 X 和肘部旋转轴是两种不同设置。

- IK Forearm：IK → MCH_IK_Hand，Pole → Pole，Chain Length=2，Iterations=500。
- IK Hand：Copy Transforms → Hand IK，World → World、Replace、Influence=1。
- 可视杆：Copy Location 跟随 IK Forearm 头（肘），再 Stretch To 指向 Pole，关闭体积补偿；仅显示。
- **Enable Stretch** 默认开；Arm/Forearm IK Stretch 默认各 0.01，分别可调。按用户最新确认保留拉伸开启；原生弹性 IK 允许长度略有变化，不能将拉伸关闭作为大臂锁轴错误的替代修复。
- **Pole Angle** 可手调；首次 Connect 后，面板数值改变须点 **Update IK Parameters**。
- 本步只接 IK 分支，Switch 仍是下一步单独接入。

### 同步手工修好的设置 / 修复旧实例

第四步的 **Sync / Repair IK Setup** 用于 0.10.4 及更早实例，或已在 Blender 原生界面手工修好但插件记录仍旧的实例。无需重建前面步骤；当前活动 Arm 实例直接点击即可，普通 Check/Load 因旧设置不一致报错时也可使用。

此明确操作读取并保留当前原生小臂唯一解锁的 IK 旋转轴、IK 约束的 Stretch、两段 Stretch 数值及 Pole Angle，同步到面板/持久记录；释放大臂所有 IK 轴，将已有 MCH_IK_Hand 解除父级，并将小臂受管 IK 的目标设为这根机制骨。它保留 Hand_IK 控制器姿态、源静止几何、原骨身份、现有约束/切换驱动以及其他步骤。不关闭用户重新开启的拉伸，不自动改 Pole Angle。小臂有零个或多个轴解锁时会要求明确设置唯一铰链轴，不猜测。

原生 Copy Transforms 仍由 MCH_IK_Hand 跟随 Hand_IK。若校准后改过锁轴，旧校准指标会失效，可在合适的参考姿态再次 Match Rest Bend。原生目标只允许在同一实例的 Hand_IK 与 MCH_IK_Hand 两个已记录身份之间迁移；其他外来目标、损坏约束、外来驱动和用户机制继续拒绝。Undo/Redo、异常回滚及保存重开均支持。只做到第三步的旧实例也可用此按钮明确迁移并连接。

### Match Rest Bend

连接 IK 后点 **Match Rest Bend**，重新摆 Pole 后可重复执行。

在临时独立两骨骨架上，根据静止肘部方向与当前实际 Hand IK/Pole 位置搜索 Pole Angle，通过 Blender 实际依赖图求值验证，再写回受管 IK 的 Pole Angle，并验证当前原骨架 IK 求值。Hand IK 在可达范围内手动调整后，静止弯曲参考投影到新肩腕线垂面。探测不改源静止几何、Roll、控制骨、姿态通道、帧、属性值或选择；临时数据总会清理。

成功阈值：弯曲方向点积至少 0.9999，临时求值的腕部目标相对误差不超过 0.002；写回后原骨架方向也须达标，肘/腕与临时求值的相对误差不超过 0.002。相对误差以两段静止总长归一化。原生 Stretch 可略微改变长度，所以不强制肘部等于未拉伸的解析肘点。

明确限制：

- 支持左右、无后缀、不同 Roll、静止骨架朝向、对象旋转、正均匀缩放、重新摆 Pole。
- 近直静止链、Pole 位于肩腕线、目标近伸直/完全折叠/不可达、零长度或数值不稳定时拒绝，保留旧角度。
- 校准时 IK Arm/Forearm 姿态通道中立；IK 根祖先处于静止状态且无约束。不支持额外 IK Limit/Stiffness、非均匀或负对象缩放、Shear，明确报错。
- 校准的限制避免复杂外部机制下写入错误角度。基础 Connect IK、手调 Pole Angle 不要求自动校准。
- 不改 Roll、不应用新静止姿态、不移动控制骨、不插关键帧。

## 5. Connect IK/FK Switch

选择 **Property Bone**（默认尝试 Properties）。

- New 默认名 Arm_FK_IK.L/.R；无侧为 Arm_FK_IK；可自定义名字。整数、范围 0..1、默认及初值 0，说明为 **0=FK、1=IK**。
- Existing 可输入已有属性名并显式确认 **0 = FK, 1 = IK**。要求整数 0/1、UI 范围恰为 0..1，拒绝明确写有反向语义的说明。不改已有值、范围、说明、默认值、动画或驱动。
- 每根 Switch 两个 Copy Transforms：先 **OZO FK** 固定 1，后 **OZO IK** 由同一个属性驱动；全部 World/World、Replace。显示名附实例所有权令牌。
- 驱动变量 ik_fk，表达式 ik_fk == 1；根据实际属性骨/属性名正确转义路径。三个 Switch 共享同一属性。
- 再次 Connect 检查并跳过，不覆盖属性、不增约束/驱动。完成后面板可直接调该属性。

这是基础约束切换，不做动画无跳匹配、自动关键帧、烘焙或已有动画补偿。

## 状态、持久记录与恢复

每步显示 Not complete / Complete / Needs inspection。控制/IK 面板数值与已应用值不一致时显示 Pending explicit update。Check/Details 给出具体骨名和计数，控制台有完整结果。Edit Mode 用 Check 同步最新编辑后验证。Load 恢复已应用参数，不重置手工生成骨几何。

JSON 记录存于 Armature 的 ozo_arm_records，与旧工具记录分离。稳定骨骼身份为 ozo_rig_identity。记录包含角色、来源几何、生成骨、原父级/Connected、步骤、受管约束/设置、驱动链接和校准指标。实际集合存于生成骨；面板设置也按 Armature 持久保存。

允许修改生成骨静止几何、根父级和控制骨父级；Tweak→Switch、三段内部父子关系和规定 Connected 须保留。来源几何、生成骨 Deform、受管约束顺序/参数/目标、属性/驱动签名受检查。删除/同名替换、损坏记录、共享/链接/只读数据、名称/动画路径冲突、明显同骨架父级/约束/变换驱动环明确报错。任意跨对象或脚本依赖图不作完整证明。

每个操作支持原生 Undo/Redo。异常时移除本次生成内容，恢复本次触及的父级、Connected、几何、身份、约束、驱动、IK 参数、属性、记录及面板设置。不会静默删除整个实例或重建损坏结构；可 Undo、恢复先前文件或手工恢复后 Check。不会将用户机制当成受管内容覆盖。约束身份依据记录、骨骼身份、令牌、设置和顺序；完全一致的手工替代品在重开后无法区分。

不会自动保存 blend。层级变化可能改变已有动画求值；保留动画数据不等于保证旧动画视觉一致。

## 开发、测试与安装

独立模块 arm.py，按 __init__.py 现有方式注册；复用 rig_common.py 身份、上下文和事务原语。原 Tweak/FK、Socket、Rotation Follow 后端不变。

在独立 --factory-startup --background Blender 5.2.2 中运行 tests/test_arm_blender.py 和 tests/test_arm_edgecases.py。覆盖五步真实求值、校准、手工映射、原动画/驱动保留、属性复用/冲突、多个实例、改名/缺失、每步保存重开、数值更新、部分失败回滚、每步 Undo/Redo、多对象 Edit/Pose 选择恢复。另有 ZIP 安装、完整模块热重载和旧功能回归。只使用合成骨架，不加载或修改用户原角色。

0.10.4 的 tests/test_arm_pole_alignment.py 另以独立 EditBone 复制/平移/挤出构造作为几何参照，验证左右侧、Roll、对象变换、已有实例修正、实际 IK 求值、Undo/Redo、保存重开和部分失败回滚。报告为 outputs/arm_pole_alignment_report.json。用户示例仅通过 MCP 只读采集坐标，求值测试在新建骨架上进行。

0.10.5 的 tests/test_arm_bending.py 进一步在实际三维示例坐标、左右侧、不同 Roll 和朝向上连续移动目标靠近肩部再远离，验证实际屈肘、目标到达，以及拉伸开/关选择保留、手工设置同步、父级/目标迁移、失败回滚、Undo/Redo 与重开续作。

构建沿用 dev/zip_build.py。入口与 manifest 版本均为 0.10.5。Blender Preferences → Add-ons → Install from Disk，选择 dist/OZO_Tools-0.10.5.zip。替换旧扩展后重启 Blender 或重载插件，再打开原有文件继续。
