import os
import win32com.client as win32

def clean_filename(title):
    invalid_chars = r'\/:*?"<>|'
    for ch in invalid_chars:
        title = title.replace(ch, '_')
    return title.strip().strip('.')

def create_docs_from_lines_win32(txt_file_path, output_dir="output_docs_win32"):
    os.makedirs(output_dir, exist_ok=True)
    word = None
    count = 0
    try:
        # 启动 Word（确保已安装 Office）
        word = win32.gencache.EnsureDispatch('Word.Application')
        word.Visible = False  # 不显示窗口
        print(txt_file_path)

        with open(txt_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for idx, line in enumerate(lines, start=1):
            title = line.strip()
            print(title)
            if not title:
                continue

            safe_title = clean_filename(title)
            # 限制文件名长度
            if len(safe_title) > 50:
                safe_title = safe_title[:50]
            filename = f"{idx:03d}_{safe_title}.doc"  # 或 .docx
            filepath = os.path.join(output_dir, filename)

            doc = word.Documents.Add()
            # 添加标题段落
            para = doc.Paragraphs.Add()
            para.Range.Text = title
            para.Range.Font.Size = 24
            para.Range.Font.Bold = True
            para.Range.Font.Color = win32.constants.wdColorBlue
            para.Range.Font.Name = "微软雅黑"
            para.Alignment = win32.constants.wdAlignParagraphCenter
            para.Range.InsertParagraphAfter()

            # 可添加额外内容
            # doc.Content.InsertAfter("正文内容...")

            doc.SaveAs(filepath)
            doc.Close()
            count += 1
            print(f"已生成: {filepath}")

        print(f"全部完成！共生成 {count} 个文档，保存在 '{output_dir}'。")
    except Exception as e:
        print(e)
    finally:
        # 无论是否出错，都释放 Word 进程
        if word is not None:
            word.Quit()



if __name__ == '__main__':
    # 请修改为你的文本文件路径
    create_docs_from_lines_win32('E:\\zsd\\zsd.txt','E:\\zsd\\zsd')
