# chuanliuspeed

#### 介绍
一款最接近真实速度的本地化部署网络测速工具，所用原理为下载网络上真实文件资源，记录下载文件大小和下载时间，计算最终下载速度。最接近真实的含义，即该速度本来就是你的网络真实下载速度。

![主界面](https://github.com/createacode/chuanliuspeed/blob/main/%E4%B8%BB%E7%95%8C%E9%9D%A2.png)

# 川流测速工具 - 完整开发文档

## 项目概述

### 1.1 项目简介
网络测速工具是一个基于Python Flask开发的Web应用程序，用于测试多个下载源的网络下载速度。该工具提供直观的Web界面，支持多源并发测试、实时进度监控、智能结果分析和数据持久化存储。

### 1.2 核心功能
- **多源并发测试**：支持同时测试多个下载源的下载速度
- **实时监控**：显示下载进度、已耗时和实时速度
- **智能分析**：自动计算平均速度（去除最高最低值）
- **配置管理**：支持下载源的增删改查和验证
- **数据持久化**：自动保存测试结果和操作日志
- **超时处理**：单个源159秒超时自动跳过
- **跨平台**：支持Windows、macOS、Linux系统

### 1.3 技术栈
- **后端**：Python 3.13 + Flask
- **前端**：HTML5 + CSS3 + JavaScript
- **打包工具**：PyInstaller
- **网络库**：requests

## 系统架构

### 2.1 目录结构
```
网络测速工具/
├── app.py                    # 主程序入口
├── download_url.json         # 下载源配置文件（自动生成）
├── requirements.txt          # Python依赖包列表
├── templates/               # 前端模板目录
│   └── index.html           # 主界面
├── static/                  # 静态资源目录
├── 下载临时/                # 临时下载文件存储目录
├── 结果/                    # 测试结果存储目录
└── 日志/                    # 日志文件存储目录
```

### 2.2 模块设计
```
┌─────────────────────────────────────────────────┐
│                   前端界面                       │
│  (HTML/CSS/JS - 用户交互和数据展示)             │
└─────────────────┬───────────────────────────────┘
                  │ HTTP请求/响应
┌─────────────────▼───────────────────────────────┐
│                  Flask服务器                     │
│  (路由处理、请求分发、模板渲染)                  │
└──────┬────────────────────┬─────────────────────┘
       │                    │
┌──────▼──────┐    ┌───────▼────────┐
│ API处理模块  │    │  配置管理模块   │
│ • 测试控制    │    │ • 加载/保存配置 │
│ • 状态查询    │    │ • 源验证       │
│ • 配置更新    │    │ • 文件大小检测 │
└──────┬──────┘    └───────┬────────┘
       │                    │
┌──────▼────────────────────▼──────┐
│          核心测试引擎             │
│  • 多线程下载                    │
│  • 进度监控                     │
│  • 超时处理                     │
│  • 速度计算                     │
└──────────────┬───────────────────┘
               │
┌──────────────▼───────────────────┐
│          数据存储模块             │
│  • 测试结果保存                  │
│  • 操作日志记录                  │
│  • 临时文件管理                  │
└──────────────────────────────────┘
```

## 后端详细设计

### 3.1 配置文件管理

#### 3.1.1 配置文件格式
```python
{
    "source_id": {
        "name": "源名称",
        "url": "下载链接",
        "size": "文件大小",
        "enabled": true,
        "valid": false,
        "last_validation": "上次验证时间",
        "last_status": "最后状态"
    },
    ...
}
```

#### 3.1.2 配置管理函数
```python
# 加载配置
def load_config():
    """从download_url.json加载配置文件"""

# 保存配置
def save_config():
    """保存配置到download_url.json"""

# 验证下载源
def validate_url(url, timeout=10):
    """验证URL是否可用"""
```

### 3.2 下载测试引擎

#### 3.2.1 下载函数
```python
def download_file(source_id, url, file_path, progress_callback=None, speed_callback=None):
    """
    下载文件函数
    
    参数:
        source_id: 源ID
        url: 下载链接
        file_path: 临时文件路径
        progress_callback: 进度回调函数
        speed_callback: 速度回调函数
    
    返回:
        download_time: 下载时间(秒)
        speed_mbps: 速度(Mbps)
        speed_mbs: 速度(MB/s)
        downloaded_size: 已下载大小
        status: 状态信息
    """
```

#### 3.2.2 进度监控机制
```python
# 进度回调示例
def progress_callback(source_id, progress):
    """更新下载进度"""
    test_results[source_id]['progress'] = progress

# 速度回调示例  
def speed_callback(source_id, speed_mbps, speed_mbs, elapsed_time):
    """更新实时速度"""
    test_results[source_id].update({
        'current_speed_mbps': speed_mbps,
        'current_speed_mbs': speed_mbs,
        'elapsed_time': elapsed_time
    })
```

#### 3.2.3 超时处理
```python
# 超时检查
timeout = 59  # 59秒超时
if time.time() - start_time > timeout:
    return None, None, None, None, "超时(59秒)"
```

### 3.3 API接口设计

#### 3.3.1 主要API端点
```python
# 获取配置
@app.route('/api/config', methods=['GET'])
def get_config()

# 验证下载源
@app.route('/api/validate', methods=['POST'])
def validate_sources()

# 开始测试
@app.route('/api/test', methods=['POST'])
def start_test()

# 停止测试
@app.route('/api/stop', methods=['POST'])
def stop_testing()

# 获取测试状态
@app.route('/api/status', methods=['GET'])
def get_test_status()

# 更新配置
@app.route('/api/config/update', methods=['POST'])
def update_config()

# 重置测试状态
@app.route('/api/reset', methods=['POST'])
def reset_test()
```

#### 3.3.2 API响应格式
```json
{
    "success": true,
    "message": "操作成功",
    "data": {
        // 具体数据
    }
}
```

### 3.4 数据存储模块

#### 3.4.1 测试结果保存
```python
def save_test_result(test_id, results):
    """
    保存测试结果
    
    参数:
        test_id: 测试ID (格式: YYYYMMDD_HHMMSS_RANDOM4)
        results: 测试结果字典
    """
```

#### 3.4.2 日志记录
```python
def log_action(action):
    """记录用户操作日志"""
    # 格式: YYYY-MM-DD HH:MM:SS 操作描述
```

### 3.5 多线程管理

#### 3.5.1 线程池管理
```python
# 使用ThreadPoolExecutor管理并发验证
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    future_to_source = {}
    for source_id in sources_to_validate:
        future = executor.submit(validate_url, url)
        future_to_source[future] = source_id
```

#### 3.5.2 活跃下载跟踪
```python
active_downloads = {}  # 存储活跃下载进程

def stop_all_downloads():
    """停止所有下载进程"""
    for source_id in list(active_downloads.keys()):
        active_downloads[source_id]['active'] = False
```

## 前端详细设计

### 4.1 页面结构

#### 4.1.1 HTML结构
```html
<div class="container">
    <!-- 头部 -->
    <header>...</header>
    
    <!-- 平均速度显示区 -->
    <div class="average-display">...</div>
    
    <!-- 控制面板 -->
    <div class="control-panel">...</div>
    
    <!-- 主要内容区 -->
    <div class="main-content">
        <!-- 下载源配置区 -->
        <div class="panel">...</div>
        
        <!-- 测试结果区 -->
        <div class="panel">...</div>
    </div>
    
    <!-- 页脚 -->
    <div class="footer">...</div>
</div>
```

#### 4.1.2 响应式布局
```css
/* 桌面端 */
.main-content {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
}

/* 移动端 */
@media (max-width: 1024px) {
    .main-content {
        grid-template-columns: 1fr;
    }
}
```

### 4.2 JavaScript核心模块

#### 4.2.1 状态管理
```javascript
// 全局状态
let sources = {};               // 下载源数据
let selectedSources = new Set(); // 选中的源
let isTesting = false;          // 测试状态
let currentTestId = null;       // 当前测试ID
let pollingInterval = null;     // 轮询间隔
let validationInProgress = false; // 验证状态
```

#### 4.2.2 数据加载和渲染
```javascript
// 加载下载源
async function loadSources() {
    const response = await fetch('/api/config');
    const data = await response.json();
    if (data.success) {
        sources = data.sources;
        renderSourcesList();
    }
}

// 渲染下载源列表
function renderSourcesList() {
    // 遍历sources对象，生成HTML
}
```

#### 4.2.3 测试控制
```javascript
// 开始测试
async function startTest() {
    if (selectedSources.size === 0) {
        showNotification('请选择至少一个下载源', 'error');
        return;
    }
    
    const response = await fetch('/api/test', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sources: Array.from(selectedSources)})
    });
    
    // 处理响应
}
```

#### 4.2.4 实时更新
```javascript
// 开始轮询测试状态
function startPolling() {
    pollingInterval = setInterval(async () => {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        if (data.success) {
            updateTestResults(data.results, data.avg_speed_mbps, 
                              data.avg_speed_mbs, data.calculation_process);
        }
    }, 500); // 每500毫秒轮询一次
}
```

### 4.3 用户交互

#### 4.3.1 按钮功能
| 按钮 | 功能 | 状态控制 |
|------|------|----------|
| 开始测试 | 启动测试 | 测试中禁用 |
| 重新测试 | 重置并重新测试 | 测试中禁用 |
| 停止测试 | 停止当前测试 | 非测试中禁用 |
| 验证链接 | 验证所有下载源 | 验证中禁用 |

#### 4.3.2 下载源操作
- **选择/取消选择**：点击复选框
- **全选/全不选**：顶部复选框
- **编辑**：点击编辑图标 ✏️
- **删除**：点击删除图标 🗑️
- **添加**：点击添加按钮 ➕

### 4.4 实时数据显示

#### 4.4.1 进度条组件
```javascript
function createProgressBar(progress) {
    return `
        <div class="progress-container">
            <div class="progress-header">
                <span>下载进度</span>
                <span>${progress.toFixed(1)}%</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: ${progress}%"></div>
            </div>
        </div>
    `;
}
```

#### 4.4.2 速度统计
```javascript
function createSpeedStats(elapsed_time, speed_mbps, speed_mbs) {
    return `
        <div class="progress-stats">
            <div class="stat-item">
                <div>已耗时</div>
                <div class="stat-value">${elapsed_time.toFixed(1)}s</div>
            </div>
            <div class="stat-item">
                <div>实时速度</div>
                <div class="stat-value">${speed_mbps.toFixed(2)}<br>Mbps</div>
            </div>
            <div class="stat-item">
                <div>实时速度</div>
                <div class="stat-value">${speed_mbs.toFixed(2)}<br>MB/s</div>
            </div>
        </div>
    `;
}
```

## 算法设计

### 5.1 平均速度计算算法

#### 5.1.1 算法步骤
```
1. 收集所有成功测试源的速度数据
2. 如果有效数据数量 > 2:
   a. 对速度数据进行排序
   b. 去掉最高值（索引 -1）
   c. 去掉最低值（索引 0）
   d. 剩余数据计算平均值
3. 如果有效数据数量 ≤ 2:
   a. 直接计算平均值（不去除极值）
4. 返回计算结果
```

#### 5.1.2 Python实现
```python
def calculate_average_speed(results):
    valid_results_mbps = []
    valid_results_mbs = []
    
    # 收集有效数据
    for result in results.values():
        if result['status'] == '成功' and result['time'] is not None:
            valid_results_mbps.append(result['speed_mbps'])
            valid_results_mbs.append(result['speed_mbs'])
    
    if len(valid_results_mbps) > 2:
        # 去除最高最低值
        valid_results_mbps.sort()
        valid_results_mbs.sort()
        valid_results_mbps = valid_results_mbps[1:-1]
        valid_results_mbs = valid_results_mbs[1:-1]
    
    if valid_results_mbps:
        avg_mbps = sum(valid_results_mbps) / len(valid_results_mbps)
        avg_mbs = sum(valid_results_mbs) / len(valid_results_mbs)
        return avg_mbps, avg_mbs
    else:
        return 0, 0
```

### 5.2 文件大小检测算法

#### 5.2.1 检测策略
```
1. 尝试HEAD请求获取Content-Length
2. 如果失败，尝试带Range头的GET请求
3. 如果失败，尝试读取部分数据推断大小
4. 如果都失败，返回"未知大小"
```

#### 5.2.2 实现优化
```python
def get_file_size_from_url(url, timeout=10):
    """改进的文件大小检测"""
    strategies = [
        # 策略1: HEAD请求
        lambda: requests.head(url, headers=headers, timeout=timeout),
        # 策略2: 带Range头的GET请求
        lambda: requests.get(url, headers={**headers, 'Range': 'bytes=0-1'}, timeout=timeout),
        # 策略3: 部分读取
        lambda: requests.get(url, headers=headers, timeout=timeout, stream=True)
    ]
    
    for strategy in strategies:
        try:
            response = strategy()
            # 解析大小
            size = parse_content_length(response)
            if size > 0:
                return format_file_size(size)
        except:
            continue
    
    return "未知大小"
```

### 5.3 实时速度计算算法

#### 5.3.1 计算原理
```
实时速度 = Δ数据量 / Δ时间

其中:
Δ数据量 = 当前下载量 - 上次下载量
Δ时间 = 当前时间 - 上次时间
```

#### 5.3.2 实现代码
```python
def update_speed(source_id, current_size, last_size, last_time):
    current_time = time.time()
    time_diff = current_time - last_time
    size_diff = current_size - last_size
    
    if time_diff > 0:
        # 计算bps
        speed_bps = size_diff / time_diff
        # 转换为Mbps
        speed_mbps = speed_bps * 8 / 1_000_000
        # 转换为MB/s
        speed_mbs = speed_bps / (1024 * 1024)
        
        return speed_mbps, speed_mbs, current_time
    return 0, 0, last_time
```

## 部署和打包

### 6.1 环境准备

#### 6.1.1 依赖安装
```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

#### 6.1.2 requirements.txt
```
Flask==2.3.3
requests==2.31.0
```

### 6.2 开发模式运行

#### 6.2.1 直接运行
```bash
python app.py
```

#### 6.2.2 调试模式
```bash
# Windows
set FLASK_DEBUG=1
python app.py

# Linux/macOS
export FLASK_DEBUG=1
python app.py
```

### 6.3 打包为可执行文件

#### 6.3.1 使用PyInstaller
```bash
# 基本打包
pyinstaller --onefile --name=网络测速工具 app.py

# 完整打包（包含模板和静态文件）
pyinstaller --onefile \
    --name=网络测速工具 \
    --add-data="templates;templates" \
    --add-data="static;static" \
    --icon=icon.ico \
    app.py
```

#### 6.3.2 打包选项说明
| 选项 | 说明 |
|------|------|
| `--onefile` | 打包为单个可执行文件 |
| `--name` | 指定输出文件名 |
| `--add-data` | 添加额外文件/目录 |
| `--icon` | 设置应用图标 |
| `--noconsole` | 不显示控制台窗口（Windows） |

#### 6.3.3 打包脚本
```python
# build.py
import PyInstaller.__main__
import os

PyInstaller.__main__.run([
    'app.py',
    '--onefile',
    '--name=网络测速工具',
    '--add-data=templates;templates',
    '--add-data=static;static',
    '--clean',
    '--noconsole'  # Windows下隐藏控制台
])
```

### 6.4 生产环境部署

#### 6.4.1 独立运行
```bash
# 直接运行打包后的程序
./网络测速工具
```

#### 6.4.2 作为Windows服务
```batch
:: 创建快捷方式
:: 右键 -> 发送到 -> 桌面快捷方式
```

#### 6.4.3 启动参数
```bash
# 指定端口
网络测速工具 --port 8888

# 指定主机
网络测速工具 --host 0.0.0.0
```

## 配置说明

### 7.1 默认下载源配置

#### 7.1.1 内置下载源
```json[注意：示例中wps源为超时示例，sougou源为不可用示例，使用者各根据自身维护可用源]
{
    "wps": {
        "name": "WPS Office",
        "url": "https://official-package.wpscdn.cn/wps/download/WPS_Setup_24034.exe"
    },
    "360": {
        "name": "360安全卫士",
        "url": "https://sfdl.360safe.com/pclianmeng/n/1__4002009.exe"
    },
    "qq": {
        "name": "QQ PC版",
        "url": "https://dldir1v6.qq.com/qqfile/qq/QQNT/Windows/QQ_9.9.25_251203_x64_01.exe"
    },
    "baidu": {
        "name": "百度网盘",
        "url": "https://issuecdn.baidupcs.com/issue/netdisk/yunguanjia/BaiduNetdisk_7.60.5.106.exe"
    },
    "dingtalk": {
        "name": "钉钉",
        "url": "https://dtapp-pub.dingtalk.com/dingtalk-desktop/win_installer/Release/DingTalk_v7.5.20.3019101.exe"
    },
    "netease": {
        "name": "网易云音乐",
        "url": "https://d1.music.126.net/dmusic/NeteaseCloudMusic_Music_official_3.2.5.20200428_32.exe"
    },
    "sogou": {
        "name": "搜狗输入法",
        "url": "https://cdn-fast.ime.sogou.com/sogou_pinyin_15.12c.exe"
    },
    "xunlei": {
        "name": "迅雷",
        "url": "https://down.sandai.net/thunder11/XunLeiSetup11.3.12.1902.exe"
    }
}
```

### 7.2 配置文件位置

#### 7.2.1 自动生成的目录
```
项目根目录/
├── download_url.json     # 主配置文件
├── 下载临时/            # 临时文件目录
├── 结果/                # 测试结果目录
└── 日志/                # 日志文件目录
```

#### 7.2.2 日志文件
- **系统日志**: `日志/测速工具_YYYYMMDD.log`
- **操作日志**: `日志/用户操作_YYYYMMDD.log`
- **格式**: `YYYY-MM-DD HH:MM:SS [LEVEL] 消息`

#### 7.2.3 测试结果文件
- **文件名**: `YYYYMMDD_HHMMSS_RANDOM4_测试结果.txt`
- **包含内容**:
  1. 测试配置信息
  2. 每个源的详细结果
  3. 平均速度计算过程
  4. 最终平均速度

## 使用说明

### 8.1 首次使用

#### 8.1.1 启动步骤
1. 运行可执行文件 `网络测速工具.exe`
2. 自动打开浏览器访问 `http://localhost:8400`
3. 等待自动验证下载源完成

#### 8.1.2 界面说明
```
┌─────────────────────────────────────────────────────────────┐
│ 📶 网络测速工具                                              │
│ 多源并发测速 · 智能结果分析 · 实时监控                      │
├─────────────────────────────────────────────────────────────┤
│ 平均下载速度（实时更新）               [当前时间]            │
│     436.24 Mbps           52.00 MB/s                        │
│     ┌───────────────────────────────────────────────────┐  │
│     │ 计算时间: 2024-01-11 20:09:09                     │  │
│     │ 有效测试源数量: 5                                 │  │
│     │ ...                                               │  │
│     └───────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│ [▶️ 开始测试] [🔄 重新测试] [⏹️ 停止测试] [🔍 验证链接]    │
├─────────────────────────────────────────────────────────────┤
│ 📥 下载源配置                 │ 📊 测试结果                 │
│ ┌─────────────────────────┐   │ ┌─────────────────────────┐ │
│ │ ☑ 全选/全不选           │   │ │ 测试ID: 20240111_200909 │ │
│ │                         │   │ │ [测试中: 0 已完成: 0    │ │
│ │ ☐ WPS Office (146.3 MB) │   │ │  成功率: 0%]            │ │
│ │ ☑ 360安全卫士 (85.2 MB) │   │ │                         │ │
│ │ ...                     │   │ │ WPS Office              │ │
│ │                         │   │ │ 文件大小: 146.3 MB      │ │
│ │                         │   │ │ ████████████ 75.5%      │ │
│ │                         │   │ │ 已耗时: 12.3s           │ │
│ └─────────────────────────┘   │ └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 操作流程

#### 8.2.1 基本测试流程
1. **验证下载源**（自动或手动）
2. **选择下载源**（勾选复选框）
3. **开始测试**（点击"开始测试"按钮）
4. **监控进度**（查看实时进度和速度）
5. **查看结果**（测试完成后查看平均速度）

#### 8.2.2 高级操作
1. **重新测试**: 重置状态并重新开始
2. **停止测试**: 强制停止当前测试
3. **管理下载源**: 添加、编辑、删除下载源
4. **查看历史**: 在"结果"文件夹查看历史记录

### 8.3 测试结果解读

#### 8.3.1 速度单位说明
- **Mbps**: 兆比特每秒（网络速度常用单位）
- **MB/s**: 兆字节每秒（文件传输常用单位）
- **换算关系**: 1 MB/s = 8 Mbps

#### 8.3.2 结果文件示例
```
测速测试结果 - 20240111_200909_4224
==================================================

测试配置:
测试时间: 2024-01-11 20:09:09
测试源数量: 8

详细结果:
--------------------------------------------------------------------------------
名称: WPS Office
URL: https://official-package.wpscdn.cn/wps/download/WPS_Setup_24034.exe
文件大小: 146.3 MB
已下载大小: 146.3 MB
状态: 成功
下载时间: 12.34 秒
下载速度: 436.24 Mbps / 52.00 MB/s
--------------------------------------------------------------------------------
...

平均速度计算过程:
--------------------------------------------------------------------------------
计算时间: 2024-01-11 20:09:45
有效测试源数量: 5
原始速度数据(Mbps): [385.24, 412.56, 436.24, 452.18, 478.92]
去掉最高值: 478.92 Mbps
去掉最低值: 385.24 Mbps
处理后速度数据(Mbps): [412.56, 436.24, 452.18]
平均下载速度: 436.24 Mbps / 52.00 MB/s

最终平均下载速度: 436.24 Mbps / 52.00 MB/s
```

## 故障排除

### 9.1 常见问题

#### 9.1.1 无法启动
- **问题**: 双击exe文件无反应
- **解决**:
  1. 检查系统是否安装Microsoft Visual C++ Redistributable
  2. 以管理员身份运行
  3. 检查防火墙设置

#### 9.1.2 浏览器无法访问
- **问题**: 无法打开 `http://localhost:8400`
- **解决**:
  1. 检查端口8400是否被占用
  2. 手动在浏览器输入地址
  3. 检查防火墙是否允许连接

#### 9.1.3 下载源验证失败
- **问题**: 所有下载源都显示"不可用"
- **解决**:
  1. 检查网络连接
  2. 尝试手动验证（点击"验证链接"）
  3. 检查代理设置

#### 9.1.4 测试速度异常
- **问题**: 测试速度远低于实际网络速度
- **解决**:
  1. 检查下载源服务器状态
  2. 尝试不同时间测试
  3. 选择多个源同时测试

### 9.2 性能优化

#### 9.2.1 内存管理
- 定期清理临时文件
- 控制并发下载数量
- 限制日志文件大小

#### 9.2.2 网络优化
- 使用连接池
- 设置合理的超时时间
- 启用压缩传输

## 开发指南

### 10.1 扩展功能

#### 10.1.1 添加新功能模块
```python
# 1. 在后端添加API端点
@app.route('/api/new_feature', methods=['POST'])
def new_feature():
    # 实现功能逻辑
    pass

# 2. 在前端添加交互
function newFeature() {
    // JavaScript实现
}
```

#### 10.1.2 自定义下载源
```python
# 通过配置文件添加
{
    "my_source": {
        "name": "自定义源",
        "url": "https://example.com/file.exe",
        "size": "待验证",
        "enabled": true,
        "valid": false
    }
}
```

### 10.2 代码规范

#### 10.2.1 Python代码规范
- 遵循PEP 8规范
- 使用类型注解
- 添加文档字符串

#### 10.2.2 JavaScript代码规范
- 使用ES6+语法
- 遵循Airbnb代码规范
- 使用async/await处理异步

### 10.3 测试和调试

#### 10.3.1 单元测试
```python
# test_app.py
import unittest
from app import app, validate_url

class TestApp(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
    
    def test_validate_url(self):
        result = validate_url("https://example.com")
        self.assertIsInstance(result, bool)
```

#### 10.3.2 调试技巧
```python
# 启用调试模式
app.run(debug=True)

# 日志调试
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 附录

### A. 快捷键参考

| 快捷键 | 功能 |
|--------|------|
| Ctrl+R | 刷新页面 |
| Ctrl+F5 | 强制刷新 |
| Ctrl+Shift+R | 重新测试 |
| Ctrl+Shift+S | 停止测试 |

### B. 文件格式说明

#### B.1 配置文件格式
```json
{
    "source_id": {
        "name": "string",          // 源名称
        "url": "string",           // 下载链接
        "size": "string",          // 文件大小
        "enabled": boolean,        // 是否启用
        "valid": boolean,          // 是否有效
        "last_validation": "string", // 上次验证时间
        "last_status": "string"    // 最后状态
    }
}
```

#### B.2 测试结果格式
```
测速测试结果 - [测试ID]
==================================================

测试配置:
测试时间: [时间]
测试源数量: [数量]

详细结果:
--------------------------------------------------------------------------------
名称: [名称]
URL: [链接]
文件大小: [大小]
已下载大小: [大小]
状态: [状态]
[如果成功:]
下载时间: [时间] 秒
下载速度: [速度] Mbps / [速度] MB/s
--------------------------------------------------------------------------------
...

平均速度计算过程:
--------------------------------------------------------------------------------
[计算步骤]
最终平均下载速度: [速度] Mbps / [速度] MB/s
```

### C. 技术指标

#### C.1 性能指标
- 最大并发下载数: 10
- 单个下载超时: 159秒
- 轮询间隔: 500毫秒
- 最大文件大小: 无限制（受内存限制）

#### C.2 系统要求
- **操作系统**: Windows 7+, macOS 10.12+, Linux
- **内存**: 最低512MB，推荐1GB
- **磁盘空间**: 最低100MB
- **网络**: 需要互联网连接

### D. 更新日志

#### v1.0 (初始版本)
- 基础测速功能
- 多源并发测试
- 简单结果展示

#### v1.1 (功能增强)
- 实时进度显示
- 文件大小检测优化
- 界面美化

#### v1.2 (稳定版本)
- 超时机制改进（59秒）
- 平均速度计算修复
- 进程管理优化

#### v1.3 (更新版本)
- 完整状态跟踪
- 计算过程显示
- 性能优化

#### v1.4 (更新版本)
#### v1.5 (更新版本)
#### v1.6 (更新版本)
#### v1.61 (当前版本)
- 功能完备
---

**声明**: 本工具仅供学习和测试使用，请勿用于商业用途。下载的文件版权归原作者所有，请遵守相关法律法规。
