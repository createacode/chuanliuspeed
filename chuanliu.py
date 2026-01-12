import os
import json
import time
import threading
import shutil
import random
import string
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
import requests
from urllib.parse import urlparse
import concurrent.futures
import logging
from logging.handlers import RotatingFileHandler
import sys
import webbrowser
import traceback
import signal
import atexit

# 判断是否被打包成exe
def is_frozen():
    return getattr(sys, 'frozen', False)

# 获取正确的资源路径
def resource_path(relative_path):
    """获取资源的正确路径，无论是否被打包"""
    if is_frozen():
        # 如果是打包后的exe，从临时目录获取资源
        base_path = sys._MEIPASS
    else:
        # 如果是直接运行.py文件，从当前目录获取
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    # 如果路径中包含'..'，需要处理
    if '..' in relative_path:
        # 对于需要写入的文件，我们放在exe所在目录
        if is_frozen():
            # 获取exe所在目录
            exe_dir = os.path.dirname(sys.executable)
            # 去掉相对路径中的'..'
            rel_path = os.path.basename(relative_path)
            return os.path.join(exe_dir, rel_path)
    
    return os.path.join(base_path, relative_path)

# 初始化Flask应用
app = Flask(__name__, static_folder='static', template_folder='templates')

# 配置文件路径 - 修改为可写的位置
if is_frozen():
    # 打包后，配置文件放在exe所在目录
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 未打包时，使用当前.py文件所在目录
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 配置文件放在exe所在目录，确保可写
CONFIG_FILE = os.path.join(BASE_DIR, 'download_url.json')

# 其他目录也放在exe所在目录
TEMP_DIR = os.path.join(BASE_DIR, '下载临时')
RESULT_DIR = os.path.join(BASE_DIR, '结果')
LOG_DIR = os.path.join(BASE_DIR, '日志')

# 创建必要的目录
for directory in [TEMP_DIR, RESULT_DIR, LOG_DIR]:
    os.makedirs(directory, exist_ok=True)

# 设置日志
log_file = os.path.join(LOG_DIR, f"测速工具_{datetime.now().strftime('%Y%m%d')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        RotatingFileHandler(log_file, maxBytes=10485760, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 全局变量
download_sources = {}
test_results = {}
current_test_id = None
is_testing = False
stop_test = False
download_threads = []
validation_in_progress = False
current_speed_data = {}  # 存储实时速度数据
active_downloads = {}  # 存储活跃的下载进程
calculation_process = ""  # 计算过程描述
last_update_time = None  # 最后更新时间

# 默认下载源配置（更新版）
DEFAULT_SOURCES = {
    "wps": {
        "name": "WPS Office",
        "url": "https://official-package.wpscdn.cn/wps/download/WPS_Setup_24034.exe",
        "size": "273.04 MB",
        "enabled": True,
        "valid": True,
        "last_validation": "",
        "last_status": ""
    },
    "360": {
        "name": "360安全卫士",
        "url": "https://sfdl.360safe.com/pclianmeng/n/1__4002009.exe",
        "size": "99.89 MB",
        "enabled": True,
        "valid": True,
        "last_validation": "",
        "last_status": ""
    },
    "qq": {
        "name": "QQ PC版",
        "url": "https://dldir1v6.qq.com/qqfile/qq/QQNT/Windows/QQ_9.9.25_251203_x64_01.exe",
        "size": "269.22 MB",
        "enabled": True,
        "valid": True,
        "last_validation": "",
        "last_status": ""
    },
    "baidu": {
        "name": "百度网盘",
        "url": "https://1ed9a5-3661375322.antpcdn.com:19001/b/pkg-ant.baidu.com/issue/netdisk/yunguanjia/channel/BaiduNetdisk_bdfcjd_7.60.5.106/semclickid=bd_vid_9128905482033479124_utm_account_SS-bdtg102.exe",
        "size": "473.66 MB",
        "enabled": True,
        "valid": True,
        "last_validation": "",
        "last_status": ""
    },
    "dingtalk": {
        "name": "钉钉",
        "url": "https://dtapp-pub.dingtalk.com/dingtalk-desktop/mac_dmg/Release/DingTalk_v8.2.0-Installer_51832624_arm64.dmg",
        "size": "350.08 MB",
        "enabled": True,
        "valid": True,
        "last_validation": "",
        "last_status": ""
    },
    "netease": {
        "name": "网易云音乐",
        "url": "https://d8.music.126.net/dmusic2/NeteaseCloudMusic_Music_official_3.1.25.204860_64.exe",
        "size": "152.72 MB",
        "enabled": True,
        "valid": True,
        "last_validation": "",
        "last_status": ""
    },
    "sogou": {
        "name": "搜狗输入法",
        "url": "https://ime-sec.gtimg.com/202601111830/6249aadeb11f21786d4cbc127d516a13/pc/dl/gzindex/1680521473/sogoupinyin_4.2.1.145_arm64.deb",
        "size": "链接不可用",
        "enabled": True,
        "valid": False,
        "last_validation": "",
        "last_status": ""
    },
    "xunlei": {
        "name": "迅雷",
        "url": "https://down.sandai.net/mac/thunder_5.80.4.66628.dmg",
        "size": "108.64 MB",
        "enabled": True,
        "valid": True,
        "last_validation": "",
        "last_status": ""
    }
}

def load_config():
    """加载配置文件"""
    global download_sources
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 确保配置格式正确
                for key, value in config.items():
                    if 'name' in value and 'url' in value:
                        value.setdefault('size', '')
                        value.setdefault('enabled', True)
                        value.setdefault('valid', False)
                        value.setdefault('last_validation', '')
                        value.setdefault('last_status', '')
                download_sources = config
                logger.info(f"成功加载配置文件，共 {len(download_sources)} 个下载源")
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            download_sources = DEFAULT_SOURCES.copy()
    else:
        # 使用默认配置并保存
        download_sources = DEFAULT_SOURCES.copy()
        save_config()
        logger.info("使用默认配置并创建配置文件")

def save_config():
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(download_sources, f, ensure_ascii=False, indent=2)
        logger.info("配置文件保存成功")
        return True
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
        return False

def get_file_size_from_url(url, timeout=10):
    """获取远程文件大小 - 改进版"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        }
        
        # 先尝试HEAD请求
        try:
            response = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
            
            # 处理重定向
            if response.status_code in [301, 302, 303, 307, 308]:
                redirect_url = response.headers.get('Location')
                if redirect_url:
                    if not redirect_url.startswith('http'):
                        # 处理相对URL
                        from urllib.parse import urljoin
                        redirect_url = urljoin(url, redirect_url)
                    url = redirect_url
                    response = requests.head(redirect_url, headers=headers, timeout=timeout, allow_redirects=True)
            
            if response.status_code in [200, 206]:
                # 尝试从Content-Length获取文件大小
                content_length = response.headers.get('Content-Length')
                if content_length:
                    try:
                        size_bytes = int(content_length)
                        if size_bytes > 0:
                            return format_file_size(size_bytes)
                    except:
                        pass
                
                # 尝试从Content-Range获取文件大小
                content_range = response.headers.get('Content-Range')
                if content_range and '/' in content_range:
                    try:
                        size_bytes = int(content_range.split('/')[-1])
                        if size_bytes > 0:
                            return format_file_size(size_bytes)
                    except:
                        pass
        except:
            pass
        
        # 如果HEAD失败，尝试带Range头的GET请求
        try:
            headers['Range'] = 'bytes=0-1'
            response = requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
            
            if response.status_code in [200, 206]:
                content_length = response.headers.get('Content-Length')
                if content_length:
                    try:
                        size_bytes = int(content_length)
                        if size_bytes > 0:
                            return format_file_size(size_bytes)
                    except:
                        pass
                
                # 尝试从Content-Range获取
                content_range = response.headers.get('Content-Range')
                if content_range and '/' in content_range:
                    try:
                        size_bytes = int(content_range.split('/')[-1])
                        if size_bytes > 0:
                            return format_file_size(size_bytes)
                    except:
                        pass
        except:
            pass
        
        # 最后尝试完整GET请求但只读取头部
        try:
            response = requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
            if response.status_code in [200, 206]:
                content_length = response.headers.get('Content-Length')
                if content_length:
                    try:
                        size_bytes = int(content_length)
                        if size_bytes > 0:
                            return format_file_size(size_bytes)
                    except:
                        pass
                
                # 如果还是没有，尝试读取一小部分数据来推断
                chunk_size = 1024 * 1024  # 1MB
                total_size = 0
                for chunk in response.iter_content(chunk_size=chunk_size):
                    total_size += len(chunk)
                    if len(chunk) < chunk_size:  # 最后一个块
                        break
                if total_size > 0:
                    return format_file_size(total_size)
        except:
            pass
        
        return "未知大小"
        
    except requests.exceptions.Timeout:
        logger.warning(f"获取文件大小超时: {url}")
        return "超时"
    except Exception as e:
        logger.error(f"获取文件大小失败 {url}: {e}")
        return "未知大小"

def format_file_size(size_bytes):
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes/1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes/(1024*1024):.2f} MB"
    else:
        return f"{size_bytes/(1024*1024*1024):.2f} GB"

def validate_url(url, timeout=10):
    """验证URL是否可用"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*'
        }
        
        # 先尝试HEAD请求
        try:
            response = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
            
            # 处理重定向
            if response.status_code in [301, 302, 303, 307, 308]:
                redirect_url = response.headers.get('Location')
                if redirect_url:
                    if not redirect_url.startswith('http'):
                        from urllib.parse import urljoin
                        redirect_url = urljoin(url, redirect_url)
                    url = redirect_url
                    response = requests.head(redirect_url, headers=headers, timeout=timeout, allow_redirects=True)
            
            if response.status_code in [200, 206]:
                return True
        except:
            pass
        
        # 如果HEAD不被支持，尝试GET请求
        try:
            response = requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
            if response.status_code in [200, 206]:
                return True
        except:
            pass
        
        return False
        
    except Exception as e:
        logger.error(f"验证URL失败 {url}: {e}")
        return False

def download_file(source_id, url, file_path, progress_callback=None, speed_callback=None, downloaded_size_callback=None):
    """下载文件 - 增加159秒超时，可中断"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        }
        
        start_time = time.time()
        timeout = 159  # 单个下载超时时间改为159秒
        
        # 注册这个下载为活跃下载
        active_downloads[source_id] = {
            'start_time': start_time,
            'active': True
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('Content-Length', 0))
            downloaded_size = 0
            last_progress_time = start_time
            last_speed_update_time = start_time
            last_downloaded_size = 0
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not active_downloads.get(source_id, {}).get('active', True):
                        return None, None, None, None, "用户停止"
                    
                    # 检查是否超时
                    if time.time() - start_time > timeout:
                        return None, None, None, None, "超时(59秒)"
                    
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # 更新已下载大小
                        if downloaded_size_callback:
                            downloaded_size_callback(source_id, downloaded_size)
                        
                        # 更新进度（每秒最多更新4次）
                        current_time = time.time()
                        if current_time - last_progress_time > 0.25 and progress_callback:
                            progress = (downloaded_size / total_size * 100) if total_size > 0 else 0
                            progress_callback(source_id, progress)
                            last_progress_time = current_time
                        
                        # 计算实时速度（每秒更新）
                        if current_time - last_speed_update_time >= 1.0 and speed_callback:
                            time_diff = current_time - last_speed_update_time
                            size_diff = downloaded_size - last_downloaded_size
                            if time_diff > 0:
                                current_speed_bps = size_diff / time_diff
                                current_speed_mbps = current_speed_bps * 8 / 1_000_000
                                current_speed_mbs = current_speed_bps / (1024 * 1024)
                                speed_callback(source_id, current_speed_mbps, current_speed_mbs, current_time - start_time)
                            
                            last_speed_update_time = current_time
                            last_downloaded_size = downloaded_size
            
            end_time = time.time()
            download_time = end_time - start_time
            
            if download_time > 0:
                speed_bps = downloaded_size / download_time
                speed_mbps = speed_bps * 8 / 1_000_000  # 转换为Mbps
                speed_mbs = downloaded_size / download_time / (1024 * 1024)  # 转换为MB/s
            else:
                speed_mbps = 0
                speed_mbs = 0
            
            return download_time, speed_mbps, speed_mbs, downloaded_size, "成功"
        
        except requests.exceptions.Timeout:
            return None, None, None, None, "超时(59秒)"
        except Exception as e:
            logger.error(f"下载文件失败 {url}: {e}")
            return None, None, None, None, f"错误: {str(e)}"
        finally:
            # 移除活跃下载
            if source_id in active_downloads:
                del active_downloads[source_id]
    
    except Exception as e:
        logger.error(f"下载文件异常 {url}: {e}")
        return None, None, None, None, f"异常: {str(e)}"

def stop_all_downloads():
    """停止所有下载进程"""
    for source_id in list(active_downloads.keys()):
        active_downloads[source_id]['active'] = False
    logger.info("已停止所有下载进程")

def clean_temp_dir():
    """清理临时目录"""
    try:
        for filename in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                logger.error(f"删除临时文件失败 {file_path}: {e}")
        logger.info("临时目录清理完成")
        return True
    except Exception as e:
        logger.error(f"清理临时目录失败: {e}")
        return False

def save_test_result(test_id, results):
    """保存测试结果"""
    try:
        result_file = os.path.join(RESULT_DIR, f"{test_id}_测试结果.txt")
        
        # 计算平均速度
        valid_results_mbps = []
        valid_results_mbs = []
        calculation_steps = []
        
        for result in results.values():
            if result['status'] == '成功' and result['time'] is not None:
                valid_results_mbps.append(result['speed_mbps'])
                valid_results_mbs.append(result['speed_mbs'])
        
        current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if valid_results_mbps:
            calculation_steps.append(f"计算时间: {current_time_str}")
            calculation_steps.append(f"有效测试源数量: {len(valid_results_mbps)}")
            
            if len(valid_results_mbps) > 2:
                # 去掉最高和最低值
                sorted_mbps = sorted(valid_results_mbps)
                sorted_mbs = sorted(valid_results_mbs)
                
                calculation_steps.append(f"原始速度数据(Mbps): {[round(s, 2) for s in sorted_mbps]}")
                calculation_steps.append(f"去掉最高值: {round(sorted_mbps[-1], 2)} Mbps")
                calculation_steps.append(f"去掉最低值: {round(sorted_mbps[0], 2)} Mbps")
                
                valid_results_mbps = sorted_mbps[1:-1]
                valid_results_mbs = sorted_mbs[1:-1]
                
                calculation_steps.append(f"处理后速度数据(Mbps): {[round(s, 2) for s in valid_results_mbps]}")
            else:
                calculation_steps.append(f"速度数据(Mbps): {[round(s, 2) for s in valid_results_mbps]}")
                calculation_steps.append("数据不足3个，不去除极值")
            
            avg_speed_mbps = sum(valid_results_mbps) / len(valid_results_mbps)
            avg_speed_mbs = sum(valid_results_mbs) / len(valid_results_mbs)
            
            calculation_steps.append(f"平均下载速度: {avg_speed_mbps:.2f} Mbps / {avg_speed_mbs:.2f} MB/s")
        else:
            calculation_steps.append(f"计算时间: {current_time_str}")
            calculation_steps.append("无有效测试结果")
            avg_speed_mbps = 0
            avg_speed_mbs = 0
        
        # 生成计算过程字符串
        global calculation_process, last_update_time
        calculation_process = "\n".join(calculation_steps)
        last_update_time = current_time_str
        
        with open(result_file, 'w', encoding='utf-8') as f:
            f.write(f"测速测试结果 - {test_id}\n")
            f.write("=" * 50 + "\n\n")
            
            # 写入测试配置
            f.write("测试配置:\n")
            f.write(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"测试源数量: {len(results)}\n\n")
            
            # 写入详细结果
            f.write("详细结果:\n")
            f.write("-" * 80 + "\n")
            
            for source_id, result in results.items():
                f.write(f"名称: {result['name']}\n")
                f.write(f"URL: {result['url']}\n")
                f.write(f"状态: {result['status']}\n")
                
                if result['status'] == '成功':
                    f.write(f"下载时间: {result['time']:.2f} 秒\n")
                    f.write(f"下载速度: {result['speed_mbps']:.2f} Mbps / {result['speed_mbs']:.2f} MB/s\n")
                    f.write(f"已下载大小: {format_file_size(result.get('downloaded_size', 0))}\n")
                elif '超时' in result['status']:
                    f.write(f"已下载大小: {format_file_size(result.get('downloaded_size', 0))}\n")
                f.write("-" * 80 + "\n")
            
            # 写入计算过程
            f.write("\n平均速度计算过程:\n")
            f.write("-" * 80 + "\n")
            for step in calculation_steps:
                f.write(f"{step}\n")
            
            if avg_speed_mbps > 0:
                f.write(f"\n最终平均下载速度: {avg_speed_mbps:.2f} Mbps / {avg_speed_mbs:.2f} MB/s\n")
            else:
                f.write("\n无有效测试结果\n")
        
        logger.info(f"测试结果已保存: {result_file}")
        return result_file, avg_speed_mbps, avg_speed_mbs
    
    except Exception as e:
        logger.error(f"保存测试结果失败: {e}")
        return None, 0, 0

def log_action(action):
    """记录用户操作日志"""
    try:
        log_entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {action}\n"
        action_log_file = os.path.join(LOG_DIR, f"用户操作_{datetime.now().strftime('%Y%m%d')}.log")
        
        with open(action_log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        logger.error(f"记录操作日志失败: {e}")

@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    """获取配置"""
    return jsonify({
        'success': True,
        'sources': download_sources,
        'validation_in_progress': validation_in_progress
    })

@app.route('/api/validate', methods=['POST'])
def validate_sources():
    """验证下载源"""
    global validation_in_progress
    
    try:
        data = request.json
        sources_to_validate = data.get('sources', [])
        
        # 如果没有指定源，验证所有源
        if not sources_to_validate:
            sources_to_validate = list(download_sources.keys())
        
        validation_in_progress = True
        
        # 启动验证线程
        validation_thread = threading.Thread(target=validate_sources_thread, args=(sources_to_validate,))
        validation_thread.daemon = True
        validation_thread.start()
        
        return jsonify({
            'success': True,
            'message': '验证已开始，请等待完成'
        })
    
    except Exception as e:
        logger.error(f"验证下载源失败: {e}")
        validation_in_progress = False
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

def validate_sources_thread(sources_to_validate):
    """验证下载源线程"""
    global validation_in_progress, download_sources
    
    try:
        results = {}
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 使用线程池并发验证
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_source = {}
            for source_id in sources_to_validate:
                if source_id in download_sources:
                    url = download_sources[source_id]['url']
                    future = executor.submit(validate_url, url)
                    future_to_source[future] = source_id
            
            for future in concurrent.futures.as_completed(future_to_source):
                source_id = future_to_source[future]
                try:
                    is_valid = future.result()
                    download_sources[source_id]['valid'] = is_valid
                    download_sources[source_id]['last_validation'] = current_time
                    
                    # 获取文件大小
                    if is_valid:
                        size = get_file_size_from_url(download_sources[source_id]['url'])
                        download_sources[source_id]['size'] = size
                        download_sources[source_id]['last_status'] = '验证成功'
                    else:
                        download_sources[source_id]['size'] = '链接不可用'
                        download_sources[source_id]['last_status'] = '验证失败'
                    
                    results[source_id] = {
                        'valid': is_valid,
                        'size': download_sources[source_id]['size'],
                        'last_validation': current_time,
                        'last_status': download_sources[source_id]['last_status']
                    }
                except Exception as e:
                    logger.error(f"验证源 {source_id} 失败: {e}")
                    download_sources[source_id]['valid'] = False
                    download_sources[source_id]['size'] = '验证失败'
                    download_sources[source_id]['last_validation'] = current_time
                    download_sources[source_id]['last_status'] = '验证异常'
                    results[source_id] = {
                        'valid': False,
                        'size': '验证失败',
                        'last_validation': current_time,
                        'last_status': '验证异常'
                    }
        
        # 保存配置
        save_config()
        
        logger.info(f"验证完成，共验证 {len(results)} 个源")
        
    except Exception as e:
        logger.error(f"验证线程执行失败: {e}")
    
    finally:
        validation_in_progress = False

@app.route('/api/test', methods=['POST'])
def start_test():
    """开始测试"""
    global is_testing, stop_test, current_test_id, test_results, current_speed_data, calculation_process, last_update_time
    
    if is_testing:
        return jsonify({
            'success': False,
            'message': '测试正在进行中'
        })
    
    try:
        data = request.json
        selected_sources = data.get('sources', [])
        
        if not selected_sources:
            return jsonify({
                'success': False,
                'message': '请选择至少一个下载源'
            })
        
        # 清理临时目录
        clean_temp_dir()
        
        # 生成测试ID
        current_test_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{''.join(random.choices(string.digits, k=4))}"
        
        # 重置状态
        is_testing = True
        stop_test = False
        test_results = {}
        current_speed_data = {}
        calculation_process = ""
        last_update_time = None
        
        # 记录操作
        log_action(f"开始测试 {current_test_id}")
        
        # 启动测试线程
        test_thread = threading.Thread(target=run_download_test, args=(selected_sources,))
        test_thread.daemon = True
        test_thread.start()
        
        return jsonify({
            'success': True,
            'test_id': current_test_id,
            'message': '测试已开始'
        })
    
    except Exception as e:
        logger.error(f"启动测试失败: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/api/stop', methods=['POST'])
def stop_testing():
    """停止测试"""
    global stop_test, is_testing
    
    if not is_testing:
        return jsonify({
            'success': False,
            'message': '没有正在进行的测试'
        })
    
    stop_test = True
    stop_all_downloads()
    log_action("停止测试")
    
    return jsonify({
        'success': True,
        'message': '测试停止请求已发送，正在停止所有下载...'
    })

@app.route('/api/status', methods=['GET'])
def get_test_status():
    """获取测试状态"""
    global is_testing, test_results, current_test_id, current_speed_data, calculation_process, last_update_time
    
    # 统计测试状态
    testing_count = 0
    completed_count = 0
    success_count = 0
    failed_count = 0
    
    for result in test_results.values():
        if result['status'] == '测试中...' or result['status'] == '测试中':
            testing_count += 1
        else:
            completed_count += 1
            if result['status'] == '成功':
                success_count += 1
            else:
                failed_count += 1
    
    # 计算当前平均速度
    avg_speed_mbps = 0
    avg_speed_mbs = 0
    valid_results_mbps = []
    valid_results_mbs = []
    
    current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    for result in test_results.values():
        if result['status'] == '成功' and result['time'] is not None:
            valid_results_mbps.append(result['speed_mbps'])
            valid_results_mbs.append(result['speed_mbs'])
    
    if valid_results_mbps:
        # 每测试完一个源就更新平均速度
        temp_mbps = valid_results_mbps.copy()
        temp_mbs = valid_results_mbs.copy()
        
        if len(temp_mbps) > 2:
            # 去掉最高和最低值
            temp_mbps.sort()
            temp_mbs.sort()
            temp_mbps = temp_mbps[1:-1]
            temp_mbs = temp_mbs[1:-1]
        
        avg_speed_mbps = sum(temp_mbps) / len(temp_mbps)
        avg_speed_mbs = sum(temp_mbs) / len(temp_mbs)
        
        # 生成当前计算过程（只显示最后三行）
        calculation_steps = []
        
        if len(valid_results_mbps) > 2:
            sorted_mbps = sorted(valid_results_mbps)
            calculation_steps.append(f"已去掉最高值: {round(sorted_mbps[-1], 2)} Mbps")
            calculation_steps.append(f"已去掉最低值: {round(sorted_mbps[0], 2)} Mbps")
            calculation_steps.append(f"当前有效源: {len(valid_results_mbps)} 个")
        else:
            calculation_steps.append(f"当前有效源: {len(valid_results_mbps)} 个")
            if len(valid_results_mbps) < 3:
                calculation_steps.append("数据不足3个，不去除极值")
        
        calculation_steps.append(f"当前平均速度: {avg_speed_mbps:.2f} Mbps / {avg_speed_mbs:.2f} MB/s")
        
        # 如果没有手动设置的计算过程，使用当前计算过程
        if not calculation_process:
            calculation_process = "\n".join(calculation_steps)
    
    # 如果测试完成且有最终计算过程，使用最终计算过程
    if not is_testing and test_results and calculation_process:
        # 使用保存的最终计算过程
        pass
    elif not is_testing and test_results and not calculation_process:
        # 测试完成但没有计算过程，生成一个
        if valid_results_mbps:
            calculation_steps = []
            calculation_steps.append(f"最终计算时间: {last_update_time or current_time_str}")
            calculation_steps.append(f"有效测试源数量: {len(valid_results_mbps)}")
            calculation_steps.append(f"最终平均下载速度: {avg_speed_mbps:.2f} Mbps / {avg_speed_mbs:.2f} MB/s")
            calculation_process = "\n".join(calculation_steps)
    
    return jsonify({
        'success': True,
        'is_testing': is_testing,
        'test_id': current_test_id,
        'results': test_results,
        'avg_speed_mbps': avg_speed_mbps,
        'avg_speed_mbs': avg_speed_mbs,
        'speed_data': current_speed_data,
        'calculation_process': calculation_process,
        'stats': {
            'testing_count': testing_count,
            'completed_count': completed_count,
            'success_count': success_count,
            'failed_count': failed_count
        }
    })

@app.route('/api/config/update', methods=['POST'])
def update_config():
    """更新配置"""
    try:
        data = request.json
        action = data.get('action')
        
        if action == 'add':
            name = data.get('name', '').strip()
            url = data.get('url', '').strip()
            
            if not name or not url:
                return jsonify({
                    'success': False,
                    'message': '名称和URL不能为空'
                })
            
            # 生成ID
            source_id = f"custom_{int(time.time())}_{len(download_sources)}"
            
            # 添加新源
            download_sources[source_id] = {
                'name': name,
                'url': url,
                'size': '待验证',
                'enabled': True,
                'valid': False,
                'last_validation': '',
                'last_status': ''
            }
            
            log_action(f"添加下载源: {name}")
        
        elif action == 'update':
            source_id = data.get('id')
            name = data.get('name', '').strip()
            url = data.get('url', '').strip()
            
            if source_id in download_sources:
                if name:
                    download_sources[source_id]['name'] = name
                
                if url:
                    download_sources[source_id]['url'] = url
                    download_sources[source_id]['valid'] = False
                    download_sources[source_id]['size'] = '待验证'
                    download_sources[source_id]['last_status'] = '待验证'
                
                log_action(f"更新下载源: {download_sources[source_id]['name']}")
        
        elif action == 'delete':
            source_id = data.get('id')
            if source_id in download_sources:
                name = download_sources[source_id]['name']
                del download_sources[source_id]
                log_action(f"删除下载源: {name}")
        
        elif action == 'toggle':
            source_id = data.get('id')
            enabled = data.get('enabled', True)
            
            if source_id in download_sources:
                download_sources[source_id]['enabled'] = enabled
                log_action(f"{'启用' if enabled else '禁用'}下载源: {download_sources[source_id]['name']}")
        
        elif action == 'toggle_all':
            enabled = data.get('enabled', True)
            for source_id in download_sources:
                download_sources[source_id]['enabled'] = enabled
            log_action(f"{'全选' if enabled else '全不选'}下载源")
        
        # 保存配置
        save_config()
        
        return jsonify({
            'success': True,
            'sources': download_sources
        })
    
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/api/reset', methods=['POST'])
def reset_test():
    """重置所有状态"""
    global is_testing, stop_test, test_results, current_test_id, current_speed_data, calculation_process, last_update_time
    
    # 停止当前测试
    if is_testing:
        stop_test = True
        stop_all_downloads()
        time.sleep(1)  # 等待停止
    
    # 重置所有状态
    is_testing = False
    stop_test = False
    test_results = {}
    current_test_id = None
    current_speed_data = {}
    calculation_process = ""
    last_update_time = None
    
    # 清理临时目录
    clean_temp_dir()
    
    # 重新加载配置（不清除下载源）
    load_config()
    
    log_action("重置所有状态")
    
    return jsonify({
        'success': True,
        'message': '所有状态已重置',
        'sources': download_sources
    })

def run_download_test(selected_sources):
    """运行下载测试"""
    global is_testing, stop_test, test_results, current_speed_data, calculation_process, last_update_time
    
    try:
        logger.info(f"开始下载测试，共 {len(selected_sources)} 个源")
        
        for source_id in selected_sources:
            if stop_test:
                logger.info("测试被用户停止")
                break
            
            if source_id not in download_sources:
                continue
            
            source = download_sources[source_id]
            
            if not source.get('valid', False):
                test_results[source_id] = {
                    'name': source['name'],
                    'url': source['url'],
                    'downloaded_size': 0,
                    'status': 'URL不可用',
                    'time': None,
                    'speed_mbps': 0,
                    'speed_mbs': 0,
                    'progress': 0,
                    'elapsed_time': 0,
                    'current_speed_mbps': 0,
                    'current_speed_mbs': 0
                }
                continue
            
            logger.info(f"开始测试: {source['name']}")
            
            # 初始化结果
            test_results[source_id] = {
                'name': source['name'],
                'url': source['url'],
                'downloaded_size': 0,
                'status': '测试中...',
                'time': None,
                'speed_mbps': 0,
                'speed_mbs': 0,
                'progress': 0,
                'elapsed_time': 0,
                'current_speed_mbps': 0,
                'current_speed_mbs': 0
            }
            
            # 生成临时文件名
            filename = os.path.basename(urlparse(source['url']).path) or f"download_{source_id}"
            temp_file = os.path.join(TEMP_DIR, filename)
            
            # 下载文件
            def progress_callback(source_id, progress):
                # 更新进度
                if source_id in test_results:
                    test_results[source_id]['progress'] = progress
            
            def speed_callback(source_id, speed_mbps, speed_mbs, elapsed_time):
                # 更新实时速度和已耗时
                if source_id in test_results:
                    test_results[source_id]['current_speed_mbps'] = speed_mbps
                    test_results[source_id]['current_speed_mbs'] = speed_mbs
                    test_results[source_id]['elapsed_time'] = elapsed_time
                    current_speed_data[source_id] = {
                        'speed_mbps': speed_mbps,
                        'speed_mbs': speed_mbs,
                        'elapsed_time': elapsed_time
                    }
            
            def downloaded_size_callback(source_id, downloaded_size):
                # 更新已下载大小
                if source_id in test_results:
                    test_results[source_id]['downloaded_size'] = downloaded_size
            
            download_time, speed_mbps, speed_mbs, downloaded_size, status = download_file(
                source_id, source['url'], temp_file, progress_callback, speed_callback, downloaded_size_callback
            )
            
            # 更新下载源状态（特别是超时状态）
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if '超时' in status:
                download_sources[source_id]['last_status'] = f'测试超时: {status}'
                download_sources[source_id]['last_validation'] = current_time
            elif status == '成功':
                download_sources[source_id]['last_status'] = '测试成功'
                download_sources[source_id]['last_validation'] = current_time
            else:
                download_sources[source_id]['last_status'] = f'测试失败: {status}'
                download_sources[source_id]['last_validation'] = current_time
            
            # 记录结果
            test_results[source_id] = {
                'name': source['name'],
                'url': source['url'],
                'downloaded_size': downloaded_size if downloaded_size else 0,
                'status': status,
                'time': download_time,
                'speed_mbps': speed_mbps if speed_mbps else 0,
                'speed_mbs': speed_mbs if speed_mbs else 0,
                'progress': 100 if status == '成功' else 0,
                'elapsed_time': download_time if download_time else 0,
                'current_speed_mbps': 0,
                'current_speed_mbs': 0
            }
            
            # 删除临时文件
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
            
            logger.info(f"测试完成: {source['name']} - 状态: {status}")
        
        # 保存测试结果
        if test_results:
            result_file, avg_speed_mbps, avg_speed_mbs = save_test_result(current_test_id, test_results)
            logger.info(f"最终平均下载速度: {avg_speed_mbps:.2f} Mbps / {avg_speed_mbs:.2f} MB/s")
        
        # 保存更新后的配置
        save_config()
        
        logger.info("下载测试完成")
        
    except Exception as e:
        logger.error(f"下载测试执行失败: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 停止所有下载进程
        stop_all_downloads()
        is_testing = False
        current_speed_data = {}

def start_server():
    """启动服务器"""
    # 加载配置
    load_config()
    
    logger.info("服务器启动完成，监听端口 8400")
    
    # 立即打开浏览器
    webbrowser.open(f'http://localhost:8400')
    
    # 立即开始验证下载源
    logger.info("开始自动验证下载源...")
    validation_thread = threading.Thread(target=validate_sources_thread, args=(list(download_sources.keys()),))
    validation_thread.daemon = True
    validation_thread.start()
    
    # 注册退出清理
    atexit.register(stop_all_downloads)
    
    app.run(host='0.0.0.0', port=8400, debug=False)

if __name__ == '__main__':
    start_server()
