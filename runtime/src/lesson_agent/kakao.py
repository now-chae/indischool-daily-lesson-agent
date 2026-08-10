from __future__ import annotations

import json
from typing import Any

import httpx
import keyring


TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
TOKEN_SERVICE = "lesson-agent-kakao"
TOKEN_USER = "oauth-token"


class KakaoAuthRequired(RuntimeError):
    pass


class KakaoSendError(RuntimeError):
    pass


class KakaoClient:
    def __init__(
        self,
        rest_api_key: str,
        redirect_uri: str,
        *,
        link_url: str = "https://example.com",
        store: Any = keyring,
        client: httpx.Client | None = None,
    ) -> None:
        self.rest_api_key = rest_api_key
        self.redirect_uri = redirect_uri
        self.link_url = link_url
        self.store = store
        self.client = client or httpx.Client(timeout=20)

    def save_authorization_code(self, code: str) -> None:
        response = self.client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": self.rest_api_key,
                "redirect_uri": self.redirect_uri,
                "code": code,
            },
        )
        response.raise_for_status()
        self._save_tokens(response.json())

    def authorization_url(self) -> str:
        return str(
            httpx.URL("https://kauth.kakao.com/oauth/authorize").copy_merge_params(
                {
                    "client_id": self.rest_api_key,
                    "redirect_uri": self.redirect_uri,
                    "response_type": "code",
                    "scope": "talk_message",
                }
            )
        )

    def send_to_me(self, messages: list[str]) -> list[str]:
        tokens = self._load_tokens()
        request_ids: list[str] = []
        for message in messages:
            response = self._send(message, tokens["access_token"])
            if response.status_code == 401:
                tokens = self._refresh(tokens)
                response = self._send(message, tokens["access_token"])
            if response.status_code == 401:
                raise KakaoAuthRequired("카카오 재인증이 필요합니다.")
            if response.is_error:
                raise KakaoSendError(f"카카오 메시지 전송 실패: HTTP {response.status_code}")
            payload = response.json()
            if payload.get("result_code") not in (None, 0):
                raise KakaoSendError(f"카카오 메시지 전송 실패: {payload.get('result_code')}")
            request_ids.append(str(payload.get("request_id", "")))
        return request_ids

    def _send(self, message: str, access_token: str) -> httpx.Response:
        template = {
            "object_type": "text",
            "text": message,
            "link": {"web_url": self.link_url, "mobile_web_url": self.link_url},
            "button_title": "학교 홈페이지",
        }
        return self.client.post(
            SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
        )

    def _refresh(self, tokens: dict[str, str]) -> dict[str, str]:
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise KakaoAuthRequired("카카오 갱신 토큰이 없습니다.")
        response = self.client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": self.rest_api_key,
                "refresh_token": refresh_token,
            },
        )
        if response.is_error:
            raise KakaoAuthRequired("카카오 토큰 갱신에 실패했습니다.")
        updated = {**tokens, **response.json()}
        self._save_tokens(updated)
        return updated

    def _load_tokens(self) -> dict[str, str]:
        raw = self.store.get_password(TOKEN_SERVICE, TOKEN_USER)
        if not raw:
            raise KakaoAuthRequired("카카오 인증 설정이 필요합니다.")
        try:
            tokens = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise KakaoAuthRequired("저장된 카카오 인증정보를 읽을 수 없습니다.") from exc
        if not tokens.get("access_token"):
            raise KakaoAuthRequired("카카오 액세스 토큰이 없습니다.")
        return tokens

    def _save_tokens(self, tokens: dict[str, str]) -> None:
        self.store.set_password(
            TOKEN_SERVICE,
            TOKEN_USER,
            json.dumps(tokens, ensure_ascii=False),
        )
