import logging

from env import settings
from flex import db
from flex.db.model.blockchain import Asset
from flex.providers.tinyman import get_tinyman_assets_details


logger = logging.getLogger(__name__)


def assets_set_logo_url_from_tinyman_info() -> list[Asset]:
    assets = db.assets.get_all()
    logger.info(f'Setting logo_url for {len(assets)} assets from tinyman info.')

    tinyman_infos = {info.id: info for info in get_tinyman_assets_details()}
    for asset in assets:
        info = tinyman_infos.get(asset.id)
        if info is not None:
            asset.logo_url = info.logo_svg_url
        else:
            asset.logo_url = settings.asset_default_logo_url
        db.assets.update(asset)
    return assets
