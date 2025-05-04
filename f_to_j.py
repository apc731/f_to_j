import os
import sys
import argparse
import tempfile
import shutil
import zipfile
import re
from pathlib import Path
import opencc
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom

def convert_epub_to_simplified(input_path, output_path=None):
    """
    将EPUB文件从繁体转为简体
    
    Args:
        input_path: 输入EPUB文件路径
        output_path: 输出EPUB文件路径，如果为None则自动生成
    
    Returns:
        bool: 转换是否成功
    """
    print(f"🔄 开始处理文件: {input_path}")
    
    # 如果未指定输出路径，则自动生成
    if output_path is None:
        output_path = str(Path(input_path).with_suffix('')) + '_simplified.epub'
    
    # 确保输出目录存在
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    # 初始化OpenCC转换器
    try:
        converter = opencc.OpenCC('t2s')
    except Exception as e:
        try:
            # 尝试使用完整路径
            opencc_path = os.path.dirname(opencc.__file__)
            config_path = os.path.join(opencc_path, 'config', 't2s.json')
            if os.path.exists(config_path):
                converter = opencc.OpenCC(config_path)
            else:
                # 尝试使用内置转换器
                converter = opencc.OpenCC('t2s.json')
        except Exception as e:
            print(f"❌ 初始化繁简转换器失败: {e}")
            return False
    
    try:
        # 创建临时目录用于处理文件
        with tempfile.TemporaryDirectory() as temp_dir:
            extract_dir = os.path.join(temp_dir, "extract")
            os.makedirs(extract_dir, exist_ok=True)
            
            # 复制源文件到临时文件，确保源文件不被修改
            temp_file = os.path.join(temp_dir, "temp.epub")
            shutil.copy2(input_path, temp_file)
            
            # 解压EPUB文件
            try:
                with zipfile.ZipFile(temp_file, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
                print("✅ 成功解压EPUB文件")
            except Exception as e:
                print(f"❌ 解压EPUB文件失败: {e}")
                return False
            
            # 处理所有文本文件
            html_count = 0
            changed_count = 0
            
            # 处理HTML/XHTML文件
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    if file.endswith(('.xhtml', '.html', '.htm', '.xml', '.opf', '.ncx')):
                        file_path = os.path.join(root, file)
                        
                        try:
                            # 读取文件内容
                            with open(file_path, 'rb') as f:
                                content_bytes = f.read()
                            
                            # 尝试解码
                            try:
                                content = content_bytes.decode('utf-8', errors='ignore')
                            except Exception:
                                try:
                                    content = content_bytes.decode('gb18030', errors='ignore')
                                except Exception:
                                    content = content_bytes.decode('latin1', errors='ignore')
                            
                            # 保存原始XML声明和DOCTYPE
                            xml_declaration = None
                            match = re.search(r'<\?xml[^>]+\?>', content)
                            if match:
                                xml_declaration = match.group(0)
                            
                            doctype = None
                            match = re.search(r'<!DOCTYPE[^>]+>', content)
                            if match:
                                doctype = match.group(0)
                            
                            # 根据文件类型选择处理方法
                            if file.endswith(('.xhtml', '.html', '.htm')):
                                html_count += 1
                                changed, new_content = convert_html_content(content, converter)
                                
                                if changed:
                                    # 恢复XML声明和DOCTYPE
                                    if xml_declaration and not new_content.startswith('<?xml'):
                                        new_content = xml_declaration + '\n' + new_content
                                    if doctype and '<!DOCTYPE' not in new_content:
                                        if xml_declaration and new_content.startswith('<?xml'):
                                            # 在XML声明后插入DOCTYPE
                                            new_content = new_content.replace('?>\n', '?>\n' + doctype + '\n')
                                        else:
                                            new_content = doctype + '\n' + new_content
                                    
                                    # 写回文件
                                    with open(file_path, 'w', encoding='utf-8', newline='') as f:
                                        f.write(new_content)
                                    
                                    changed_count += 1
                                    print(f"✅ 已转换HTML文件: {os.path.basename(file_path)}")
                            
                            elif file.endswith(('.xml', '.opf', '.ncx')):
                                changed, new_content = convert_xml_content(content, converter)
                                
                                if changed:
                                    # 恢复XML声明
                                    if xml_declaration and not new_content.startswith('<?xml'):
                                        new_content = xml_declaration + '\n' + new_content
                                    
                                    # 写回文件
                                    with open(file_path, 'w', encoding='utf-8', newline='') as f:
                                        f.write(new_content)
                                    
                                    print(f"✅ 已转换XML文件: {os.path.basename(file_path)}")
                        
                        except Exception as e:
                            print(f"⚠️ 处理文件 {os.path.basename(file_path)} 时出错: {e}")
            
            print(f"📊 共处理 {html_count} 个HTML文件，其中 {changed_count} 个文件有变化")
            
            # 确保mimetype文件正确
            mimetype_path = os.path.join(extract_dir, 'mimetype')
            with open(mimetype_path, 'w', encoding='utf-8', newline='') as f:
                f.write('application/epub+zip')
            
            # 手动打包EPUB文件，确保WPS兼容性
            if package_epub_safely(extract_dir, output_path):
                print(f"✅ 新的简体EPUB文件已生成: {output_path}")
                return True
            else:
                print("❌ 打包EPUB文件失败")
                return False
                
    except Exception as e:
        print(f"❌ 处理过程中出错: {e}")
        return False

def convert_html_content(content, converter):
    """
    转换HTML内容中的文本，保留原始HTML结构
    
    Args:
        content: HTML内容
        converter: OpenCC转换器
    
    Returns:
        (bool, str): 是否有变化，转换后的内容
    """
    # 使用正则表达式提取和转换文本，更安全
    changed = False
    
    # 只替换标签之间的文本，不修改标签和属性
    def replace_text(match):
        nonlocal changed
        text = match.group(1)
        # 跳过纯数字、空白等内容
        if re.match(r'^[\s\d.,:;!?]+$', text):
            return match.group(0)
        new_text = converter.convert(text)
        if new_text != text:
            changed = True
            return f">{new_text}<"
        return match.group(0)
    
    # 只替换标签之间的文本
    pattern = r'>([^<>]+)<'
    new_content = re.sub(pattern, replace_text, content)
    
    return changed, new_content

def convert_xml_content(content, converter):
    """
    安全地转换XML内容中的文本
    
    Args:
        content: XML内容
        converter: OpenCC转换器
    
    Returns:
        (bool, str): 是否有变化，转换后的内容
    """
    # 使用正则表达式提取和转换文本，更安全
    changed = False
    
    # 只替换标签之间的文本，不修改标签和属性
    def replace_text(match):
        nonlocal changed
        text = match.group(1)
        # 跳过纯数字、空白等内容
        if re.match(r'^[\s\d.,:;!?]+$', text):
            return match.group(0)
        new_text = converter.convert(text)
        if new_text != text:
            changed = True
            return f">{new_text}<"
        return match.group(0)
    
    # 只替换标签之间的文本
    pattern = r'>([^<>]+)<'
    new_content = re.sub(pattern, replace_text, content)
    
    return changed, new_content

def package_epub_safely(extract_dir, output_path):
    """
    安全地打包EPUB文件，确保WPS兼容性
    
    Args:
        extract_dir: 解压目录
        output_path: 输出文件路径
    
    Returns:
        bool: 是否成功
    """
    try:
        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        # 确保输出文件不存在
        if os.path.exists(output_path):
            os.remove(output_path)
        
        # 使用zipfile库手动控制打包过程
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zipf:
            # 首先添加mimetype文件，不压缩
            mimetype_path = os.path.join(extract_dir, 'mimetype')
            if os.path.exists(mimetype_path):
                zipf.write(mimetype_path, 'mimetype', compress_type=zipfile.ZIP_STORED)
            else:
                # 如果不存在，创建一个
                zipf.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
            
            # 添加META-INF目录下的文件，不压缩
            meta_inf_dir = os.path.join(extract_dir, 'META-INF')
            if os.path.exists(meta_inf_dir):
                for root, dirs, files in os.walk(meta_inf_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, extract_dir)
                        # 统一路径分隔符为正斜杠（EPUB标准）
                        rel_path = rel_path.replace(os.sep, '/')
                        zipf.write(file_path, rel_path, compress_type=zipfile.ZIP_STORED)
            
            # 添加其他文件
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    if file == 'mimetype' or root.startswith(meta_inf_dir):
                        continue  # 已经添加过了
                    
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, extract_dir)
                    
                    # 统一路径分隔符为正斜杠（EPUB标准）
                    rel_path = rel_path.replace(os.sep, '/')
                    
                    # 添加文件
                    zipf.write(file_path, rel_path, compress_type=zipfile.ZIP_DEFLATED)
        
        # 验证生成的文件
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            try:
                with zipfile.ZipFile(output_path, 'r') as zip_ref:
                    # 检查是否可以列出文件
                    file_list = zip_ref.namelist()
                    if 'mimetype' not in file_list:
                        print("⚠️ 警告：生成的EPUB文件缺少mimetype文件")
                        return False
                return True
            except Exception as e:
                print(f"❌ 验证生成的EPUB文件失败: {e}")
                return False
        else:
            print("❌ 生成的EPUB文件不存在或为空")
            return False
    
    except Exception as e:
        print(f"❌ 打包EPUB文件时出错: {e}")
        return False

def main():
    """
    主函数
    """
    print("📚 EPUB繁体转简体转换工具 (专业版) 📚")
    print("-----------------------------------")
    
    # 检查必要的库是否已安装
    try:
        import opencc
    except ImportError as e:
        print(f"❌ 缺少必要的库: {e}")
        print("请安装所需的库:")
        print("pip install opencc-python-reimplemented")
        return
    
    # 使用命令行参数
    parser = argparse.ArgumentParser(description="EPUB繁体转简体转换工具")
    parser.add_argument("epub_file", nargs="?", help="EPUB文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径")
    args = parser.parse_args()
    
    # 从命令行参数获取文件路径
    epub_file = args.epub_file
    output_file = args.output
    
    # 如果没有提供命令行参数，则请求用户输入
    if not epub_file:
        epub_file = input("请输入EPUB文件路径: ").strip('"')
    
    if not os.path.exists(epub_file):
        print(f"❌ 文件不存在: {epub_file}")
        return
    
    # 转换文件
    success = convert_epub_to_simplified(epub_file, output_file)
    
    if success:
        print("✅ 转换完成！")
    else:
        print("❌ 转换失败！")

if __name__ == "__main__":
    main()