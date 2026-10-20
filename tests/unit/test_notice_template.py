from garmin_hub.garmin_accounts import notice
from garmin_hub.web.templating import TEMPLATES_DIR


def test_current_notice_template_exists() -> None:
    assert (TEMPLATES_DIR / notice.template_name()).is_file()
    assert notice.template_name() == f"garmin/notice_v{notice.NOTICE_VERSION}.html"


def test_wrapper_template_exists() -> None:
    assert (TEMPLATES_DIR / "garmin" / "notice.html").is_file()
