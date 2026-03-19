import io
from pathlib import Path

import pdfplumber
import pandas as pd
from aidial_client import Dial
from bs4 import BeautifulSoup


class DialFileContentExtractor:

    def __init__(self, endpoint: str, api_key: str):
        self.dial_client = Dial(
            base_url=endpoint,
            api_key=api_key,
        )

    def extract_text(self, file_url: str) -> str:
        response = self.dial_client.files.download(file_url)
        filename = response.filename
        content = response.content
        extension = Path(filename).suffix.lower()
        return self.__extract_text(content, extension, filename)

    def __extract_text(self, file_content: bytes, file_extension: str, filename: str) -> str:
        """Extract text content based on file type."""
        try:
            if file_extension == '.txt':
                return file_content.decode('utf-8', errors='ignore')
            if file_extension == '.pdf':
                pdf = io.BytesIO(file_content)
                text = []
                with pdfplumber.open(pdf) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text.append(page_text)
                return '\n\n'.join(text)
            if file_extension == '.csv':
                content = file_content.decode('utf-8', errors='ignore')
                csv_buffer = io.StringIO(content)
                dataframe = pd.read_csv(csv_buffer)
                return dataframe.to_markdown(index=False)
            if file_extension in ['.html', '.htm']:
                content = file_content.decode('utf-8', errors='ignore')
                soup = BeautifulSoup(content, 'html.parser')
                for script in soup(["script", "style"]):
                    script.decompose()

                return soup.get_text(separator='\n', strip=True)
            else:
                return file_content.decode('utf-8', errors='ignore')

        except Exception as e:
            print(f"Error extracting text from {filename}: {str(e)}")
            return ""