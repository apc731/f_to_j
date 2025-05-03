import os
import opencc
import zipfile
import shutil
import chardet
import logging
import tempfile
import re
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from datetime import datetime

# 配置日志
log_file = f"epub_convert_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename=log_file,
    filemode='w'
)

def convert_epub(epub_file_path):
    """
    将EPUB文件从繁体转为简体
    """
    logging.info(f"开始处理文件: {epub_file_path}")
    
    # 创建源文件备份
    backup_file = epub_file_path.replace('.epub', '_backup.epub')
    if not os.path.exists(backup_file):
        shutil.copy2(epub_file_path, backup_file)
        print(f"✅ 已创建源文件备份: {backup_file}")
        logging.info(f"已创建源文件备份: {backup_file}")
    
    # 初始化 OpenCC（繁体转简体）- 修复配置文件路径问题
    try:
        # 尝试直接使用配置名称
        converter = opencc.OpenCC('t2s')
    except Exception as e:
        logging.warning(f"使用't2s'初始化OpenCC失败: {e}")
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
            logging.error(f"初始化OpenCC失败: {e}")
            print(f"❌ 初始化繁简转换器失败: {e}")
            return False
    
    # 使用临时目录而不是固定目录
    with tempfile.TemporaryDirectory() as extract_dir:
        logging.info(f"创建临时目录: {extract_dir}")
        
        # 1. 解压 epub 到临时目录
        try:
            with zipfile.ZipFile(epub_file_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
                logging.info("成功解压EPUB文件")
        except Exception as e:
            logging.error(f"解压EPUB文件失败: {e}")
            print(f"❌ 解压EPUB文件失败: {e}")
            return False
        
        # 检查EPUB结构
        if not validate_epub_structure(extract_dir):
            logging.warning("EPUB结构验证失败，但将继续尝试转换")
            print("⚠️ EPUB结构验证失败，但将继续尝试转换")
        
        # 2. 转换所有文本文件为简体（极保守方式）
        file_count = 0
        changed_count = 0
        
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if file.endswith(('.xhtml', '.html', '.htm', '.xml', '.opf', '.ncx')):
                    file_path = os.path.join(root, file)
                    try:
                        # 检测原始编码
                        with open(file_path, 'rb') as f:
                            raw = f.read()
                        
                        # 保存原始文件属性和内容（用于恢复）
                        original_stat = os.stat(file_path)
                        original_content = raw
                        
                        detect = chardet.detect(raw)
                        encoding = detect['encoding'] if detect['encoding'] and detect['confidence'] > 0.7 else 'utf-8'
                        logging.info(f"文件 {file} 检测到编码: {encoding}, 置信度: {detect['confidence'] if 'confidence' in detect else 'unknown'}")
                        
                        # 尝试解码
                        try:
                            content = raw.decode(encoding, errors='ignore')
                        except Exception as e:
                            logging.warning(f"使用检测到的编码 {encoding} 解码失败，尝试使用 utf-8: {e}")
                            content = raw.decode('utf-8', errors='ignore')
                        
                        file_count += 1
                        
                        # 检查文件类型并尝试转换
                        try:
                            if file.endswith(('.xhtml', '.html', '.htm')):
                                # HTML类文件使用BeautifulSoup处理
                                changed = convert_html_content(content, file_path, converter)
                            elif file.endswith(('.xml', '.opf', '.ncx')):
                                # XML类文件使用正则表达式处理，更安全
                                changed = convert_xml_content(content, file_path, converter)
                            else:
                                changed = False
                            
                            if changed:
                                changed_count += 1
                                # 恢复原始文件属性
                                os.utime(file_path, (original_stat.st_atime, original_stat.st_mtime))
                        except Exception as e:
                            # 转换失败，恢复原始内容
                            logging.error(f"转换文件 {file_path} 失败，恢复原始内容: {e}")
                            with open(file_path, 'wb') as f:
                                f.write(original_content)
                    
                    except Exception as e:
                        logging.error(f"处理文件 {file_path} 时出错: {e}")
                        print(f"⚠️ 跳过无法处理的文件 {file_path}，原因：{e}")
        
        logging.info(f"共处理 {file_count} 个文件，其中 {changed_count} 个文件有变化")
        print(f"📊 共处理 {file_count} 个文件，其中 {changed_count} 个文件有变化")
        
        # 3. 重新打包为新的 epub 文件，确保符合epub标准
        simplified_epub = epub_file_path.replace('.epub', '_simplified.epub')
        
        # 确保mimetype文件正确
        ensure_mimetype_file(extract_dir)
        
        # 使用更安全的打包方法
        if not package_epub_safely(extract_dir, simplified_epub):
            logging.error("打包EPUB文件失败")
            print("❌ 打包EPUB文件失败")
            return False
        
        # 4. 验证结果
        if os.path.exists(simplified_epub) and os.path.getsize(simplified_epub) > 0:
            logging.info(f"成功生成简体EPUB文件: {simplified_epub}")
            print(f"✅ 新的简体EPUB文件已生成: {simplified_epub}")
            return True
        else:
            logging.error("生成简体EPUB文件失败")
            print("❌ 转换失败，源文件保持原样")
            print(f"⚠️ 请检查备份文件: {backup_file}")
            return False

def validate_epub_structure(extract_dir):
    """
    验证EPUB文件结构
    """
    # 检查mimetype文件
    mimetype_path = os.path.join(extract_dir, 'mimetype')
    if not os.path.exists(mimetype_path):
        logging.warning("缺少mimetype文件，将创建")
        return True  # 我们会在后面创建
    
    # 检查META-INF目录
    meta_inf_dir = os.path.join(extract_dir, 'META-INF')
    if not os.path.exists(meta_inf_dir):
        logging.error("缺少META-INF目录")
        os.makedirs(meta_inf_dir)
        
    # 检查META-INF/container.xml
    container_xml = os.path.join(extract_dir, 'META-INF', 'container.xml')
    if not os.path.exists(container_xml):
        logging.error("缺少关键文件 META-INF/container.xml")
        # 尝试查找OPF文件并创建container.xml
        opf_files = []
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if file.endswith('.opf'):
                    rel_path = os.path.relpath(os.path.join(root, file), extract_dir)
                    rel_path = rel_path.replace(os.sep, '/')
                    opf_files.append(rel_path)
        
        if opf_files:
            create_container_xml(container_xml, opf_files[0])
            logging.info(f"已创建container.xml，指向: {opf_files[0]}")
            return True
        return False
    
    # 检查OPF文件
    try:
        with open(container_xml, 'r', encoding='utf-8', errors='ignore') as f:
            container_content = f.read()
        
        # 查找OPF文件路径
        match = re.search(r'full-path="([^"]+)"', container_content)
        if match:
            opf_path = match.group(1)
            opf_full_path = os.path.join(extract_dir, *opf_path.split('/'))
            if not os.path.exists(opf_full_path):
                logging.error(f"OPF文件不存在: {opf_path}")
                return False
            logging.info(f"找到OPF文件: {opf_path}")
        else:
            logging.error("无法在container.xml中找到OPF文件路径")
            return False
    except Exception as e:
        logging.error(f"检查OPF文件时出错: {e}")
        return False
    
    return True

def create_container_xml(container_path, opf_path):
    """
    创建container.xml文件
    """
    content = f'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="{opf_path}" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>'''
    
    os.makedirs(os.path.dirname(container_path), exist_ok=True)
    with open(container_path, 'w', encoding='utf-8') as f:
        f.write(content)

def convert_html_content(content, file_path, converter):
    """
    转换HTML内容中的文本
    """
    # 保存原始XML声明和DOCTYPE
    xml_declaration = None
    match = re.search(r'<\?xml[^>]+\?>', content)
    if match:
        xml_declaration = match.group(0)
    
    doctype = None
    match = re.search(r'<!DOCTYPE[^>]+>', content)
    if match:
        doctype = match.group(0)
    
    # 尝试不同的解析器
    parsers = ['html.parser', 'lxml', 'html5lib']
    soup = None
    
    for parser in parsers:
        try:
            soup = BeautifulSoup(content, parser)
            break
        except Exception as e:
            logging.warning(f"使用解析器 {parser} 解析 {file_path} 失败: {e}")
    
    if soup is None:
        logging.error(f"所有解析器都无法解析 {file_path}")
        return False
    
    changed = False
    
    # 只替换文本节点
    for elem in soup.find_all(string=True):
        if isinstance(elem, NavigableString):
            parent = elem.parent
            # 跳过script/style等
            if parent and parent.name in ['script', 'style']:
                continue
            
            # 转换文本
            original_text = str(elem)
            new_text = converter.convert(original_text)
            
            if new_text != original_text:
                elem.replace_with(new_text)
                changed = True
    
    # 只在有变化时写回
    if changed:
        # 获取原始文件编码
        with open(file_path, 'rb') as f:
            raw = f.read()
        detect = chardet.detect(raw)
        encoding = detect['encoding'] if detect['encoding'] and detect['confidence'] > 0.7 else 'utf-8'
        
        # 写回文件
        with open(file_path, 'w', encoding=encoding, newline='', errors='ignore') as f:
            output = str(soup)
            
            # 恢复XML声明和DOCTYPE
            if xml_declaration and not output.startswith('<?xml'):
                output = xml_declaration + '\n' + output
            if doctype and '<!DOCTYPE' not in output:
                if xml_declaration and output.startswith('<?xml'):
                    # 在XML声明后插入DOCTYPE
                    output = output.replace('?>\n', '?>\n' + doctype + '\n')
                else:
                    output = doctype + '\n' + output
            
            f.write(output)
        
        logging.info(f"已转换文件: {file_path}")
    
    return changed

def convert_xml_content(content, file_path, converter):
    """
    安全地转换XML内容中的文本
    """
    # 保存原始XML声明
    xml_declaration = None
    match = re.search(r'<\?xml[^>]+\?>', content)
    if match:
        xml_declaration = match.group(0)
    
    # 使用更安全的方法处理XML
    # 只替换纯文本内容，不修改属性值
    changed_content = content
    
    # 使用正则表达式提取和转换文本，更安全
    def replace_text(match):
        text = match.group(1)
        # 跳过纯数字、空白等内容
        if re.match(r'^[\s\d.,:;!?]+$', text):
            return match.group(0)
        new_text = converter.convert(text)
        if new_text != text:
            return f">{new_text}<"
        return match.group(0)
    
    # 只替换标签之间的文本
    pattern = r'>([^<>]+)<'
    new_content = re.sub(pattern, replace_text, changed_content)
    
    changed = new_content != content
    
    if changed:
        # 获取原始文件编码
        with open(file_path, 'rb') as f:
            raw = f.read()
        detect = chardet.detect(raw)
        encoding = detect['encoding'] if detect['encoding'] and detect['confidence'] > 0.7 else 'utf-8'
        
        # 写回文件
        with open(file_path, 'w', encoding=encoding, newline='', errors='ignore') as f:
            # 如果有XML声明且不在输出中，添加回去
            if xml_declaration and not new_content.startswith('<?xml'):
                new_content = xml_declaration + '\n' + new_content
            f.write(new_content)
        
        logging.info(f"已转换XML文件: {file_path}")
    
    return changed

def ensure_mimetype_file(extract_dir):
    """
    确保mimetype文件正确
    """
    mimetype_path = os.path.join(extract_dir, 'mimetype')
    
    # 创建或更新mimetype文件
    with open(mimetype_path, 'wb') as f:
        f.write(b'application/epub+zip')
    
    logging.info("已确保mimetype文件正确")

def package_epub_safely(extract_dir, output_path):
    """
    更安全地打包EPUB文件
    """
    try:
        # 创建一个临时目录，用于存放要打包的文件
        with tempfile.TemporaryDirectory() as temp_dir:
            # 复制所有文件到临时目录
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    if file in ['.DS_Store', 'Thumbs.db']:
                        continue
                    
                    src_path = os.path.join(root, file)
                    rel_path = os.path.relpath(src_path, extract_dir)
                    dst_path = os.path.join(temp_dir, rel_path)
                    
                    # 确保目标目录存在
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    shutil.copy2(src_path, dst_path)
            
            # 确保mimetype文件正确
            mimetype_path = os.path.join(temp_dir, 'mimetype')
            with open(mimetype_path, 'wb') as f:
                f.write(b'application/epub+zip')
            
            # 使用外部工具打包（如果可用）
            if shutil.which('zip'):
                # 使用zip命令行工具，确保mimetype不被压缩且在第一位
                current_dir = os.getcwd()
                try:
                    os.chdir(temp_dir)
                    os.system(f'zip -X0 "{output_path}" mimetype')
                    os.system(f'zip -Xr9D "{output_path}" * -x mimetype')
                    os.chdir(current_dir)
                    return os.path.exists(output_path)
                except Exception as e:
                    logging.error(f"使用zip命令打包失败: {e}")
                    os.chdir(current_dir)
            
            # 如果外部工具不可用，使用Python的zipfile
            mimetype_path = os.path.join(temp_dir, 'mimetype')
            
            with zipfile.ZipFile(output_path, 'w') as zipf:
                # mimetype必须第一个且未压缩
                zipf.write(mimetype_path, 'mimetype', compress_type=zipfile.ZIP_STORED)
                
                # 添加其他文件
                for foldername, subfolders, filenames in os.walk(temp_dir):
                    for filename in filenames:
                        if filename in ['.DS_Store', 'Thumbs.db', 'mimetype']:
                            continue
                        
                        abs_path = os.path.join(foldername, filename)
                        rel_path = os.path.relpath(abs_path, temp_dir)
                        
                        # 统一路径分隔符
                        rel_path = rel_path.replace(os.sep, '/')
                        
                        # 特殊文件不压缩
                        if rel_path == 'META-INF/container.xml':
                            zipf.write(abs_path, rel_path, compress_type=zipfile.ZIP_STORED)
                        else:
                            zipf.write(abs_path, rel_path, compress_type=zipfile.ZIP_DEFLATED)
            
            logging.info(f"成功打包EPUB文件: {output_path}")
            return True
    except Exception as e:
        logging.error(f"打包EPUB文件时出错: {e}")
        return False

def main():
    """
    主函数
    """
    print("📚 EPUB繁体转简体转换工具 📚")
    print("----------------------------")
    
    # 可以改为从命令行参数获取
    epub_file = r"C:\Users\86184\Downloads\毛澤東之後的中國：一個強國崛起的真相 = China After Mao The Rise of a Superpower (馮客 (Frank Dikötter) 著, 蕭葉 譯) (Z-Library).epub"
    
    # 也可以让用户输入文件路径
    # epub_file = input("请输入EPUB文件路径: ").strip('"')
    
    if not os.path.exists(epub_file):
        print(f"❌ 文件不存在: {epub_file}")
        return
    
    print(f"🔄 开始处理文件: {epub_file}")
    success = convert_epub(epub_file)
    
    if success:
        print("✅ 转换完成！")
    else:
        print("❌ 转换失败！")
    
    print(f"📝 详细日志已保存至: {log_file}")

if __name__ == "__main__":
    main()
