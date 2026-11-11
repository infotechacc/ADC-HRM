from odoo.addons.web.controllers.webmanifest import WebManifest

ICON_DIR = 'odoo_branding_remover/static/img'


class BrandingWebManifest(WebManifest):
    """BinaryAid icons for the installable web app and the offline page."""

    def _get_webmanifest(self):
        manifest = super()._get_webmanifest()
        if manifest.get('name') == 'Odoo':
            manifest['name'] = 'BinaryAid HRMS'
        manifest.update(background_color='#0B5FC1', theme_color='#0B5FC1')
        manifest['icons'] = [{'src': '/%s/icon-%s.png' % (ICON_DIR, size), 'sizes': size, 'type': 'image/png'}
                             for size in ('192x192', '512x512')]
        return manifest

    def _icon_path(self):
        return '%s/icon-192x192.png' % ICON_DIR
