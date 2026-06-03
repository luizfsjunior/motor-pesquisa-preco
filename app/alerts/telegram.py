from abc import ABC, abstractmethod

import requests
from loguru import logger

from app.config.settings import get_settings
from app.models.schemas import PromotionAlert


class AlertSender(ABC):
    @abstractmethod
    def send_promotion(self, alert: PromotionAlert) -> bool:
        pass


class NoOpAlertSender(AlertSender):
    def send_promotion(self, alert: PromotionAlert) -> bool:
        logger.debug("Telegram disabled — alert not sent: {}", alert.alert_type)
        return False


class TelegramAlertService(AlertSender):
    API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self) -> None:
        self.settings = get_settings()

    def send_promotion(self, alert: PromotionAlert) -> bool:
        if not self.settings.telegram_enabled:
            return NoOpAlertSender().send_promotion(alert)
        text = self._format_message(alert)
        url = self.API_URL.format(token=self.settings.telegram_bot_token)
        try:
            response = requests.post(
                url,
                json={
                    "chat_id": self.settings.telegram_chat_id,
                    "text": text,
                    "disable_web_page_preview": False,
                },
                timeout=15,
            )
            response.raise_for_status()
            logger.info("Telegram alert sent: {}", alert.alert_type)
            return True
        except Exception as exc:
            logger.error("Failed to send Telegram alert: {}", exc)
            return False

    def _format_message(self, alert: PromotionAlert) -> str:
        price_fmt = f"R$ {alert.current_price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        avg_line = ""
        if alert.historical_average:
            avg_fmt = (
                f"R$ {alert.historical_average:,.2f}"
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )
            avg_line = f"\nMédia histórica: {avg_fmt}"
        discount_line = ""
        if alert.discount_percent:
            discount_line = f"\nDesconto: {alert.discount_percent:.0f}%"
        store_line = alert.store_name or "Não informada"
        return (
            "🔥 PROMOÇÃO DETECTADA\n\n"
            f"Produto: {alert.title}\n\n"
            f"Marketplace: {self._marketplace_label(alert.marketplace)}\n\n"
            f"Preço: {price_fmt}"
            f"{discount_line}"
            f"{avg_line}\n\n"
            f"Confiabilidade: {alert.trust_level.value}\n\n"
            f"Loja:\n{store_line}\n\n"
            f"Link:\n{alert.url}"
        )

    @staticmethod
    def _marketplace_label(marketplace: str) -> str:
        labels = {
            "shopee": "Shopee",
            "mercadolivre": "Mercado Livre",
            "google_shopping": "Google Shopping",
            "amazon": "Amazon Brasil",
            "kabum": "Kabum",
        }
        return labels.get(marketplace, marketplace)


def get_alert_sender() -> AlertSender:
    settings = get_settings()
    if settings.telegram_enabled:
        return TelegramAlertService()
    return NoOpAlertSender()
