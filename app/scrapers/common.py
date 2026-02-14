from base import BaseScraper


class CommonXMLScraper(BaseScraper):
    def __init__(self, chain_name: str, chain_code: str, online_store_id: str):
        self._chain_name = chain_name
        self._chain_code = chain_code
        self._online_store_id = online_store_id

    @property
    def chain_name(self) -> str:
        return self._chain_name

    @property
    def online_store(self) -> str:
        return self._online_store_id

    @property
    def chain_code(self) -> str:
        return self._chain_code

    def parse(self, file_path):
        return super().parse(file_path)
