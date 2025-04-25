# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25

import json
import random
import time
from typing import Any, Dict, List, Optional

import requests

import setting
import utils
from logger import logger

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"  # noqa: E501


class PastefyClient:
    """
    Client for interacting with the Pastefy API
    Implements CRUD operations for folders and pastes with retry mechanism
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://pastefy.app",
        max_retries: int = 3,
        max_wait: int = 10,
    ):
        """
        Initialize the Pastefy client

        Args:
            base_url: Base URL of the Pastefy API (default: https://pastefy.app)
            api_key: API key for authentication
            max_retries: Maximum number of retries for failed requests (default: 3)
            max_wait: Maximum wait time in seconds for retries (default: 10)
        """

        token = utils.trim(api_key)
        if not token:
            logger.error("API key is required")
            raise ValueError("API key is required")

        base_url = utils.trim(base_url).removesuffix("/")
        if not base_url:
            logger.error("Base URL is required")
            raise ValueError("Base URL is required")

        self.base_url = base_url
        self.api_url = f"{self.base_url}/api/v2"
        self.api_key = token
        self.max_retries = max(max_retries, 0)
        self.max_wait = max(max_wait, 0)

        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

        # Add more headers to session
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _make_request(
        self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> Any:
        """
        Make a request to the Pastefy API with retry mechanism using exponential backoff

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint
            data: Request data (optional)
            params: Query parameters (optional)

        Returns:
            Response data
        """
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        retry_count = 0

        while retry_count <= self.max_retries:
            try:
                if method.upper() == "GET":
                    response = self.session.get(url, params=params)
                elif method.upper() == "POST":
                    response = self.session.post(url, json=data, params=params)
                elif method.upper() == "PUT":
                    response = self.session.put(url, json=data, params=params)
                elif method.upper() == "DELETE":
                    response = self.session.delete(url, params=params)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()
                return response.json()
            except (requests.RequestException, json.JSONDecodeError) as e:
                retry_count += 1
                if retry_count > self.max_retries:
                    logger.error(f"Failed after {self.max_retries} retries: {str(e)}")
                    raise

                # Calculate wait time with exponential backoff and jitter
                wait_time = min(2**retry_count + random.uniform(0, 1), self.max_wait)
                logger.warning(f"Request failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)

    # Folder operations
    def create_folder(self, name: str, parent: Optional[str] = None) -> str:
        """
        Create a new folder.

        Args:
            name: Name of the folder
            parent: ID of the parent folder (optional)

        Returns:
            Created folder ID
        """
        name, parent = utils.trim(name), utils.trim(parent)
        if not name:
            logger.error("Folder name is required")
            return ""

        data = {"name": name}
        if parent:
            data["parent"] = parent

        result = self._make_request("POST", "folder", data=data)
        if not result or not isinstance(result, dict) or not result.get("success"):
            logger.error(f"Failed to create folder: {name}, response: {result}")
            return ""

        folder = result.get("folder", {})
        if not folder or not isinstance(folder, dict):
            logger.error(f"Failed to create folder: {name}, response: {result}")
            return ""

        return folder.get("id", "")

    def get_folder(self, folder_id: str) -> Dict:
        """
        Get folder details by ID.

        Args:
            folder_id: ID of the folder

        Returns:
            Folder data
        """
        folder_id = utils.trim(folder_id)
        if not folder_id:
            logger.error("Folder ID is required")
            return {}

        return self._make_request("GET", f"folder/{folder_id}")

    def delete_folder(self, folder_id: str) -> bool:
        """
        Delete a folder.

        Args:
            folder_id: ID of the folder to delete

        Returns:
            True if successful, False otherwise
        """
        folder_id = utils.trim(folder_id)
        if not folder_id:
            logger.error("Folder ID is required")
            return False

        result = self._make_request("DELETE", f"folder/{folder_id}")
        return result and isinstance(result, dict) and result.get("success")

    def get_folder_id_by_name(self, name: str, parent_id: str) -> str:
        """
        Get folder ID by name within a specific parent folder.

        Args:
            name: Name of the folder to find
            parent_id: ID of the parent folder to search in

        Returns:
            Folder ID if found, empty string otherwise
        """
        parent_id = utils.trim(parent_id)
        if not parent_id:
            logger.error("Parent folder ID is required")
            return ""

        name = utils.trim(name)
        if not name:
            logger.error("Folder name is required")
            return ""

        folder = self.get_folder(parent_id)
        if not folder or not isinstance(folder, dict):
            logger.error(f"Failed to get folder: {parent_id}")
            return ""

        children = folder.get("children", [])
        if not children or not isinstance(children, list):
            logger.warning(f"Cannot get any child from folder: {parent_id}")
            return ""

        for child in children:
            if child.get("name", "") == name:
                return child.get("id", "")

        return ""

    def list_pastes(self, folder_id: str) -> List[str]:
        """
        List pastes in a folder.

        Args:
            folder_id: ID of the folder to list pastes from

        Returns:
            List of paste IDs
        """
        folder = self.get_folder(folder_id)
        if not folder or not isinstance(folder, dict):
            logger.error(f"Failed to get folder: {folder_id}")
            return []

        pastes = folder.get("pastes", [])
        if not pastes or not isinstance(pastes, list):
            logger.warning(f"Cannot get any paste from folder: {folder_id}")
            return []

        return [paste.get("id", "") for paste in pastes]

    # Paste operations
    def create_paste(
        self,
        content: str,
        title: Optional[str] = None,
        folder: Optional[str] = None,
        encrypted: bool = False,
        visibility: str = "",
        language: Optional[str] = None,
        expire_at: Optional[str] = None,
    ) -> str:
        """
        Create a new paste.

        Args:
            content: Content of the paste
            title: Title of the paste (optional)
            folder: ID of the folder to place the paste in (optional)
            encrypted: Whether the paste should be encrypted (default: False)
            visibility: Visibility of the paste (default: UNLISTED)
            language: Programming language for syntax highlighting (optional)
            expire_at: Expiration date and time for the paste (optional)

        Returns:
            Created paste ID
        """
        content = utils.trim(content)
        if not content:
            logger.error("Paste content is required")
            return ""

        visibility = utils.trim(visibility).upper() or "UNLISTED"
        data = {"content": content, "encrypted": encrypted, "visibility": visibility, "type": "PASTE"}

        title = utils.trim(title)
        if title:
            data["title"] = title

        folder = utils.trim(folder)
        if folder:
            data["folder"] = folder

        language = utils.trim(language)
        if language:
            data["tags"] = [language]

        expire_at = utils.trim(expire_at)
        if expire_at:
            data["expire_at"] = expire_at

        result = self._make_request("POST", "paste", data=data)
        if not result or not isinstance(result, dict) or not result.get("success"):
            logger.error(f"Failed to create paste: {title}, content: {content[:50]}, response: {result}")
            return ""

        paste = result.get("paste", {})
        if not paste or not isinstance(paste, dict):
            logger.error(f"Failed to create paste: {title}, content: {content[:50]}, response: {result}")
            return ""

        return paste.get("id", "")

    def get_paste(self, paste_id: str) -> Dict:
        """
        Get paste details by ID.

        Args:
            paste_id: ID of the paste

        Returns:
            Paste data
        """
        paste_id = utils.trim(paste_id)
        if not paste_id:
            logger.error("Paste ID is required")
            return {}

        return self._make_request("GET", f"paste/{paste_id}")

    def get_paste_content(self, paste_id: str) -> str:
        """
        Get the content of a paste.

        Args:
            paste_id: ID of the paste

        Returns:
            Paste content
        """
        paste_id = utils.trim(paste_id)
        if not paste_id:
            logger.error("Paste ID is required")
            return ""

        url = f"{self.base_url}/{paste_id}/raw"
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Referer": self.base_url, "Origin": self.base_url}

        # make a get request and retry if failed
        retry_count = 0
        while retry_count <= self.max_retries:
            try:
                response = self.session.get(url, headers=headers)
                response.raise_for_status()
                content = response.text
                return content.encode("utf-8", "ignore").decode("utf-8")
            except requests.RequestException as e:
                if e.response.status_code == 404:
                    logger.error(f"Paste not found: {paste_id}")
                    return ""

                retry_count += 1
                if retry_count > self.max_retries:
                    logger.error(f"Failed after {self.max_retries} retries: {str(e)}")
                    raise

                wait_time = min(2**retry_count + random.uniform(0, 1), self.max_wait)
                logger.warning(f"Request failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}")
                raise

        return ""

    def update_paste(
        self,
        paste_id: str,
        content: Optional[str] = None,
        title: Optional[str] = None,
        folder: Optional[str] = None,
        encrypted: Optional[bool] = None,
        visibility: Optional[str] = None,
        language: Optional[str] = None,
        expire_at: Optional[str] = None,
    ) -> bool:
        """
        Update a paste.

        Args:
            paste_id: ID of the paste to update
            content: New content for the paste (optional)
            title: New title for the paste (optional)
            folder: New folder ID for the paste (optional)
            encrypted: Whether the paste should be encrypted (optional)
            visibility: Visibility of the paste (optional)
            language: Programming language for syntax highlighting (optional)
            expire_at: Expiration date and time for the paste (optional)

        Returns:
            True if successful, False otherwise
        """
        paste_id = utils.trim(paste_id)
        if not paste_id:
            logger.error("Paste ID is required")
            return False

        data = {"type": "PASTE"}

        content = utils.trim(content)
        if content:
            data["content"] = content

        title = utils.trim(title)
        if title:
            data["title"] = title

        folder = utils.trim(folder)
        if folder:
            data["folder"] = folder

        if encrypted is not None:
            data["encrypted"] = encrypted

        visibility = utils.trim(visibility).upper()
        if visibility:
            data["visibility"] = visibility

        language = utils.trim(language)
        if language:
            data["tags"] = [language]

        expire_at = utils.trim(expire_at)
        if expire_at:
            data["expire_at"] = expire_at

        result = self._make_request("PUT", f"paste/{paste_id}", data=data)
        return result and isinstance(result, dict) and result.get("success")

    def delete_paste(self, paste_id: str) -> bool:
        """
        Delete a paste.

        Args:
            paste_id: ID of the paste to delete

        Returns:
            True if successful, False otherwise
        """
        paste_id = utils.trim(paste_id)
        if not paste_id:
            logger.error("Paste ID is required")
            return False

        result = self._make_request("DELETE", f"paste/{paste_id}")
        return result and isinstance(result, dict) and result.get("success")


client = PastefyClient(setting.PASTEFY_API_KEY, setting.BASE_URL, setting.MAX_RETRIES, setting.MAX_WAIT)
