import base64
import os
import tempfile
from typing import List

import requests
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
from loguru import logger

from core.server_settings import server_settings
from loader.doc_loader import DocLoader
from loader.excel_loader import ExcelLoader
from loader.image_loader import ImageLoader
from loader.pdf_loader import PDFLoader
from loader.ppt_loader import PPTLoader
from loader.text_loader import TextLoader
from runnable.base_chunk_runnable import BaseChunkRunnable
from user_types.file_chunk_request import FileChunkRequest


class FileChunkRunnable(BaseChunkRunnable):
    def __init__(self):
        pass

    def parse(self, request: FileChunkRequest) -> List[Document]:
        try:
            content = base64.b64decode(request.file.encode("utf-8"))
            file_name, file_type = os.path.splitext(request.file_name)
            logger.debug(f"待处理文件名：{file_name}, 文件类型：{file_type}")

            pure_filename = file_name.split("/")[-1]

            if file_type == ".txt":
                return self._handle_text_file(content, file_name, request)
            else:
                return self._handle_other_file_types(content, file_type, pure_filename, request)
        except Exception as e:
            logger.error(f"解析文件失败: {e}")
            return []

    def _handle_text_file(self, content: bytes, file_name: str, request: FileChunkRequest) -> List[Document]:
        try:
            logger.debug(f"[{file_name}]格式为文本文件，尝试使用 utf-8 解码")
            text_content = content.decode('utf-8')
        except UnicodeDecodeError:
            logger.warning(f"utf-8 解码失败，尝试使用 gbk 解码")
            text_content = content.decode('gbk')

        with tempfile.NamedTemporaryFile(delete=True) as f:
            f.write(text_content.encode())
            f.flush()
            loader = TextLoader(f.name)
            return self.parse_docs(loader.load(), request)

    def _handle_other_file_types(self, content: bytes, file_type: str, pure_filename: str, request: FileChunkRequest) -> \
            List[Document]:
        with tempfile.NamedTemporaryFile(delete=True) as f:
            if file_type == ".md":
                return self._convert_markdown_to_docx(f, content, pure_filename, file_type)

            f.write(content)
            loader = self._get_loader_by_file_type(f.name, file_type, request)
            docs = loader.load()
            return self.parse_docs(docs, request)

    def _convert_markdown_to_docx(self, f, content: bytes, pure_filename: str, file_type: str) -> List[Document]:
        try:
            logger.debug(f"[{pure_filename}]格式为Markdown,转换Word格式")
            response = requests.post(
                f"{server_settings.pandoc_server_host}/convert",
                data={"output": "docx"},
                files={"file": (pure_filename + file_type, content)},
            )
            response.raise_for_status()
            f.write(response.content)
            loader = DocLoader(f.name)
        except Exception as e:
            logger.warning("Markdown转Word失败，使用普通文本解析")
            f.write(content)
            loader = TextLoader(f.name)
        return loader.load()

    def _get_loader_by_file_type(self, file_path: str, file_type: str, request: FileChunkRequest):
        if file_type in [".ppt", ".pptx"]:
            return PPTLoader(file_path)
        elif file_type == ".pdf":
            return PDFLoader(file_path, request.ocr_provider_address, request.enable_ocr_parse)
        elif file_type in [".doc", ".docx"]:
            return DocLoader(file_path, request.ocr_provider_address, request.enable_ocr_parse)
        elif file_type in [".xls", ".xlsx"]:
            return ExcelLoader(file_path, request)
        elif file_type in [".jpg", ".png", ".jpeg"]:
            return ImageLoader(file_path, request)
        else:
            raise ValueError(f"不支持的文件类型: {file_type}")

    def instance(self):
        return RunnableLambda(self.parse).with_types(
            input_type=FileChunkRequest, output_type=List[Document]
        )
