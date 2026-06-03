from abc import ABC, abstractmethod

import requests
from loguru import logger

from app.config.settings import get_settings
from app.models.schemas import CycleDigest, PromotionAlert


class AlertSender(ABC):
    @abstractmethod
    def send_promotion(self, alert: PromotionAlert) -> bool:
        pass

    def send_cycle_digest(self, digest: CycleDigest) -> bool:
        return False

    def send_cycle_no_data(self, digest: CycleDigest) -> bool:
        return False

    def send_cycle_all_filtered(self, digest: CycleDigest) -> bool:
        return False


class NoOpAlertSender(AlertSender):
    def send_promotion(self, alert: PromotionAlert) -> bool:
        logger.debug("Telegram disabled — alert not sent: {}", alert.alert_type)
        return False

    def send_cycle_digest(self, digest: CycleDigest) -> bool:
        logger.debug("Telegram disabled — cycle digest not sent")
        return False

    def send_cycle_no_data(self, digest: CycleDigest) -> bool:
        logger.debug("Telegram disabled — no-data notice not sent")
        return False

    def send_cycle_all_filtered(self, digest: CycleDigest) -> bool:
        logger.debug("Telegram disabled — filtered-out notice not sent")
        return False


class TelegramAlertService(AlertSender):
    API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self) -> None:
        self.settings = get_settings()

    def send_promotion(self, alert: PromotionAlert) -> bool:
        if not self.settings.telegram_enabled:
            return NoOpAlertSender().send_promotion(alert)
        text = self._format_promotion_message(alert)
        return self._post_message(text, "promotion")

    def send_cycle_digest(self, digest: CycleDigest) -> bool:
        if not self.settings.telegram_enabled or not digest.lowest:
            return False
        text = self._format_digest_message(digest)
        return self._post_message(text, "cycle_digest")

    def send_cycle_no_data(self, digest: CycleDigest) -> bool:
        if not self.settings.telegram_enabled:
            return False
        text = self._format_no_data_message(digest)
        return self._post_message(text, "cycle_no_data")

    def send_cycle_all_filtered(self, digest: CycleDigest) -> bool:
        if not self.settings.telegram_enabled:
            return False
        text = self._format_all_filtered_message(digest)
        return self._post_message(text, "cycle_all_filtered")

    def _post_message(self, text: str, label: str) -> bool:
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
            logger.info("Telegram message sent: {}", label)
            return True
        except Exception as exc:
            logger.error("Failed to send Telegram message ({}): {}", label, exc)
            return False

    def _format_promotion_message(self, alert: PromotionAlert) -> str:
        price_fmt = self._format_brl(alert.current_price)
        avg_line = ""
        if alert.historical_average:
            avg_line = f"\nMédia histórica: {self._format_brl(alert.historical_average)}"
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

    def _format_digest_message(self, digest: CycleDigest) -> str:
        lowest = digest.lowest
        assert lowest is not None
        if digest.lowest_passed_filters:
            filter_note = "passou nos filtros do motor"
        elif digest.lowest_below_cap:
            cap = self._format_brl(digest.fallback_max_price)
            filter_note = (
                f"abaixo de {cap} (sem passar filtros/trust; "
                f"{digest.candidates_below_cap} oferta(s) nesta faixa)"
            )
        else:
            filter_note = "visto no scrape, mas não foi salvo (filtros/trust)"
        return (
            "📊 Resumo do ciclo (sem promoção)\n\n"
            f"Produto monitorado: {digest.main_term}\n"
            f"Coletados: {digest.scraped} | Salvos: {digest.saved} | "
            f"Rejeitados: {digest.rejected}\n"
            f"Duração: {digest.elapsed_ms // 1000}s\n\n"
            f"Menor preço neste ciclo ({filter_note}):\n\n"
            f"Título: {lowest.title}\n"
            f"Marketplace: {self._marketplace_label(lowest.marketplace)}\n"
            f"Preço total: {self._format_brl(lowest.total_price)}\n"
            f"Confiança: {lowest.trust_score}/100\n"
            f"Loja: {lowest.store_name or 'Não informada'}\n\n"
            f"Link:\n{lowest.url}"
        )

    def _format_all_filtered_message(self, digest: CycleDigest) -> str:
        mp_block = "\n".join(digest.marketplace_lines) or "  (nenhum)"
        return (
            "📊 Resumo do ciclo (sem promoção)\n\n"
            f"Produto monitorado: {digest.main_term}\n"
            f"Coletados: {digest.scraped} | Salvos: 0 | Rejeitados: {digest.rejected}\n"
            f"Duração: {digest.elapsed_ms // 1000}s\n\n"
            "Itens apareceram no scrape, mas nenhum ficou abaixo do teto "
            f"({self._format_brl(digest.fallback_max_price)}) ou passou nos filtros.\n"
            f"Ajuste `alerts.fallback_max_price` em `config/products.yaml`.\n\n"
            f"Por marketplace:\n{mp_block}"
        )

    def _format_no_data_message(self, digest: CycleDigest) -> str:
        mp_block = "\n".join(digest.marketplace_lines) or "  (nenhuma busca registrada)"
        err_block = ""
        if digest.errors:
            err_block = "\n\nErros:\n" + "\n".join(f"• {e}" for e in digest.errors[:8])
        return (
            "⚠️ Ciclo sem produtos coletados\n\n"
            f"Produto monitorado: {digest.main_term}\n"
            f"Buscas: {digest.attempts_total} | Vazias: {digest.attempts_empty} | "
            f"Falhas: {digest.attempts_failed}\n"
            f"Duração: {digest.elapsed_ms // 1000}s\n\n"
            f"Por marketplace:\n{mp_block}"
            f"{err_block}\n\n"
            "Dica: em GitHub Actions os sites costumam bloquear scrapers. "
            "Teste local com HEADLESS=false ou use VPS."
        )

    @staticmethod
    def _format_brl(value: float) -> str:
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

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
