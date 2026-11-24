# 亚马逊商品图制作 · Amazon Visual Production

把商品实拍、运营需求和竞品参考转成可以逐张验收的亚马逊主图（MAIN）、副图和 A+。运营可以用它写拍摄和设计需求，有图片生成或编辑能力的 AI 可以按同一份制作卡出图、局改和交付。适用于不同品牌和品类，每款商品使用自己的实拍、规格和卖点。

## 把这个项目交给 AI

把下面这段话和你自己的商品资料发给能读取链接的 AI。建议在你自己的工作区提供实拍与运营表。

> 请读取 https://github.com/percychen19-max/amazon-visual-production 的 README、AGENTS.md 和制作流程 SKILL.md。按这个流程处理我接下来提供的商品。先核对实拍、规格和运营要求，告诉我哪些资料够用、哪些会影响出图。需要整套图片时，先做一张最能解释买家疑问的副图，与实拍并排核对，再完成其余图位。

如果 AI 只能读取单个网页，可直接发它[制作流程原文](https://raw.githubusercontent.com/percychen19-max/amazon-visual-production/main/.agents/skills/amazon-visual-production/SKILL.md)和[制作卡模板](.agents/skills/amazon-visual-production/references/制作卡与模板.md)。也可以下载仓库，把这两份文档作为附件交给它。

**在 Codex 中使用**。下载或克隆仓库后，用 Codex 打开项目根目录。也可以把整个 `.agents/skills/amazon-visual-production/` 目录复制到自己的项目中，再输入 `$amazon-visual-production` 和本次需求。实际出图需要当前 AI 提供图片生成或编辑能力。需要保留版本时，给它一个可读写的本地工作目录。

## 每个商品准备什么

| 资料 | 写清的内容 |
| --- | --- |
| 商品与变体 | 品名、型号、实售颜色、目标站点和语言。不同 SKU 分目录。 |
| 自有实拍 | 全貌、关键结构、颜色和随附物。命名或标注拍的是哪个变体、哪个部位。 |
| 商品事实 | 尺寸、材质、容量、使用边界、包装清单，以及数据来源。估计值单独标注。 |
| 运营与竞品 | 哪些图位和卖点由运营指定，哪些交给 AI 提案。竞品参考写清要借鉴的角度、光线或信息排布。 |
| 交付要求 | 要做主图、副图还是高级 A+，各要几张，给哪个站点和模块，有无桌面或移动端规格。本次后台模板优先。 |

**只需要策划**时，可以直接要图序和单图制作卡。**需要两套高级 A+** 时，第一套按运营指定的购买理由与模块顺序制作。第二套从买家的具体疑问入手，结合竞品画面找出可以讲得更清楚的地方，再用自家商品有证据的特点回答。两套分别列出模块、画面、文案与实拍依据。

换品类时，从买家需要看清的细节重新拆图。例如，收纳品可用实物证明开合方式与可容纳的物件，支架可用侧视和接口近景说明安装方向与适配边界。容量和适配范围都以本款商品的实测资料为准。

## 制作和交付

1. 读取本款商品的资料，整理实物事实、可用照片及缺口。
2. 把每个购买疑问对应到一个图位，写明需要的证据、构图和文案。
3. 先验证最容易画错的结构，核对后按图序制作。参考竞品的构图和叙事，自有实拍决定产品外观。
4. 逐张放大并与实拍核对结构、颜色、文字和规格。局改从选定版本开始，保留旧版及前后对照。
5. 逐张交付可打开的图片，列出图位、变体、版本和尺寸。需要打包时按主副图和各套 A+ 分组。

[查看完整制作流程](.agents/skills/amazon-visual-production/SKILL.md) · [复制空白制作卡与交付模板](.agents/skills/amazon-visual-production/references/制作卡与模板.md) · [AI 项目入口](AGENTS.md)

## 可选的本地版本工具

随附的 Python 工具可以登记图片版本、检查文件规格及比较局改前后的像素。支持 macOS、Linux 和 Windows 的 WSL，需要 Python 3.9 或更高版本及 Pillow。策划和阅读文档可以直接开始。

在仓库根目录运行以下命令。使用版本工具前，参照制作流程里的 `job.json` 示例，在自己的商品工作目录创建任务清单，并把下方的路径换成它的位置。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python .agents/skills/amazon-visual-production/scripts/jobs.py --manifest /path/to/private-job/job.json status
```

可以用 `python -m unittest discover -s tests -v` 验证本地安装。测试使用临时生成的色块图片。

这个仓库只收录通用流程、空白模板、工具与测试。建议把自己的照片、运营表、制作卡和生成结果放在仓库之外的私有目录。
