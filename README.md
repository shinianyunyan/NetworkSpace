# NetworkSpace

一个基于 FOFA、Hunter、Quake API 的网络空间资产信息收集工具，支持域名、IP、企业查询，并提供交互式和命令行两种使用模式。

## 功能特性

- 🔍 **多数据源支持**：集成 FOFA、Hunter、Quake 三大网络空间搜索引擎
- 🎯 **多种查询类型**：支持域名、IP、企业（公司）查询
- 📊 **智能去重**：自动对查询结果进行去重处理
- 💾 **灵活导出**：支持导出为 CSV（完整数据）或 TXT（仅 IP/域名）
- 🖥️ **双模式操作**：支持交互式模式和命令行参数模式
- 🔐 **凭据验证**：自动验证 API 凭据的有效性
- 📁 **批量查询**：支持多目标查询（逗号分隔或文件输入）
- 🔄 **循环查询**：交互模式下支持连续查询，无需重复启动程序

## 安装

### 1. 克隆项目

```bash
git clone <repository-url>
cd NetworkSpace
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API 凭据

在项目根目录复制示例配置文件：

```bash
# Windows
copy config.example.json config.json

# Linux/Mac
cp config.example.json config.json
```

编辑 `config.json`，填入你的 API 凭据：

```json
{
  "fofa": {
    "key": "your_fofa_api_key",
    "base_url": "https://fofoapi.com"
  },
  "hunter": {
    "api_key": "your_hunter_api_key"
  },
  "quake": {
    "api_key": "your_quake_api_key"
  }
}
```

**注意**：
- FOFA 目前只需要 API Key，不再需要 email
- `base_url` 字段可选，默认使用官方地址
- 至少需要配置一个数据源的 API 凭据

## 使用方法

### 交互式模式（推荐）

启动交互式模式，程序会引导你完成查询：

```bash
python main.py -i
```

交互式模式下：
- 程序会自动检测并验证所有可用的 API 凭据
- 根据可用数据源动态调整查询选项（如 FOFA 不支持企业查询时会隐藏该选项）
- 支持多目标查询（可输入逗号分隔的目标或 `.txt` 文件路径）
- 在任意选择步骤输入 `0` 可退出程序
- 查询完成后可选择继续查询或退出

### 命令行参数模式

#### 基本查询

```bash
# 查询域名
python main.py -t domain -q example.com -s fofa

# 查询 IP
python main.py -t ip -q 1.2.3.4 -s hunter

# 查询企业
python main.py -t company -q "公司名称" -s quake

# 使用所有数据源查询
python main.py -t domain -q example.com -s all
```

#### 多目标查询

支持逗号分隔的多个目标：

```bash
python main.py -t domain -q "example.com,test.com,baidu.com" -s all
```

或从文件读取目标（每行一个）：

```bash
python main.py -t domain -q domain.txt -s all
```

#### 导出结果

```bash
# 导出为 CSV（包含所有字段）
python main.py -t domain -q example.com -s all -o results/example.csv

# 导出为 TXT（仅 IP 或域名）
python main.py -t domain -q example.com -s all -o results/example.txt

# 导出到目录（多目标查询时，每个目标单独保存）
python main.py -t domain -q "example.com,test.com" -s all -o results/
```

**注意**：
- 多目标查询时，如果指定了输出路径，每个目标的结果会保存到单独的文件中
- 文件名会自动处理特殊字符（替换为下划线）
- CSV 文件包含所有字段（host, ip, port, title, domain 等）
- TXT 文件仅包含 IP 或域名（无端口信息）

#### 参数说明

```
-t, --type      查询类型：domain / ip / company
-q, --query     查询关键字（支持逗号分隔或多个目标，或 .txt 文件路径）
-s, --source    数据源：fofa / hunter / quake / all（默认 all）
-o, --output    输出路径（可选，不指定则直接显示结果）
--page          页码（默认 1）
--size          每页数量（默认 100，Hunter 固定为 10）
--config        指定配置文件路径（默认 config.json）
-i, --interactive  交互式模式
-h, --help      显示帮助信息
```

## 查询类型说明

### Domain（域名查询）

查询指定域名相关的资产信息。

```bash
python main.py -t domain -q example.com -s all
```

### IP（IP 查询）

查询指定 IP 地址相关的资产信息。

```bash
python main.py -t ip -q 1.2.3.4 -s all
```

### Company（企业查询）

查询指定企业相关的资产信息。

**注意**：FOFA 不支持企业查询，使用 `-s all` 时只会从 Hunter 和 Quake 查询。

```bash
python main.py -t company -q "公司名称" -s hunter
```

## 数据源说明

### FOFA

- **查询类型**：支持 domain、ip（不支持 company）
- **API 文档**：参考 `API说明文档/fofa.txt`
- **配置字段**：`key`（API Key）、`base_url`（可选）

### Hunter

- **查询类型**：支持 domain、ip、company
- **API 文档**：参考 `API说明文档/hunter.txt`
- **配置字段**：`api_key`
- **特殊限制**：`page_size` 固定为 10

### Quake

- **查询类型**：支持 domain、ip、company
- **API 文档**：参考 `API说明文档/quake.txt`
- **配置字段**：`api_key`

## 输出格式

### CSV 格式

包含所有字段的完整数据：

```csv
host,ip,port,title,domain
https://example.com,1.2.3.4,443,Example Site,example.com
example.com,1.2.3.4,80,Example Site,example.com
```

### TXT 格式

仅包含 IP 或域名（无端口）：

```
1.2.3.4
example.com
```

## 去重逻辑

- **域名/企业查询**：基于 `host:port` 进行去重
- **IP 查询**：基于 `ip:port` 进行去重

每个目标的结果独立去重。

## 注意事项

1. **API 凭据**：使用前请确保已正确配置至少一个数据源的 API 凭据
2. **查询限制**：各平台可能有查询频率限制，请合理使用
3. **网络超时**：默认超时时间为 120 秒，如遇网络问题可能需要调整
4. **文件路径**：Windows 和 Linux/Mac 的文件路径格式不同，请注意区分
5. **特殊字符**：导出文件名中的特殊字符会自动替换为下划线

## 项目结构

```
NetworkSpace/
├── main.py                 # 程序入口
├── networkspace/           # 核心模块
│   ├── __init__.py
│   ├── cli.py             # 命令行接口
│   ├── clients.py         # API 客户端（FOFA/Hunter/Quake）
│   ├── config.py          # 配置管理
│   └── exporters.py       # 数据导出
├── API说明文档/            # API 文档
│   ├── fofa.txt
│   ├── hunter.txt
│   └── quake.txt
├── config.example.json     # 配置示例
├── requirements.txt        # 依赖列表
├── README.md              # 本文件
└── LICENSE                # MIT 许可证
```

## 许可证

本项目采用 [MIT License](LICENSE) 许可证。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 免责声明

本工具仅供安全研究和合法授权测试使用。使用者需遵守相关法律法规和平台服务条款，不得用于任何非法用途。作者不对使用本工具造成的任何后果承担责任。
