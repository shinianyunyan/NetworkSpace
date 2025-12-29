实现通过 fofa、hunter、quake 的 API 进行信息搜集，支持对域名、IP、企业的查询  

### 使用前准备

- **安装依赖**

```bash
pip install -r requirements.txt
```

- **配置文件（推荐，代替环境变量）**

在项目根目录复制一份示例配置：

```bash
copy config.example.json config.json  # Windows
```

然后根据你自己的 Key 修改 `config.json`：

```json
{
  "fofa": {
    "key": "your_fofa_key",
    "base_url": "https://fofoapi.com/api/v1"
  },
  "hunter": {
    "api_key": "your_hunter_key"
  },
  "quake": {
    "api_key": "your_quake_key"
  }
}
```

### 基本用法（框架阶段）

目前仅实现命令行框架，可通过以下方式查看骨架运行情况：

```bash
python main.py -t domain -q example.com -s all
```

参数说明：

- **-t / --type**: 查询类型，支持 `domain` / `ip` / `company`
- **-q / --query**: 查询关键字
- **-s / --source**: 数据源，支持 `fofa` / `hunter` / `quake` / `all`（默认 all）
- **--page**: 页码，默认 `1`
- **--size**: 每页数量，默认 `100`

后续将基于本框架补充各平台 API 调用与结果解析逻辑。
