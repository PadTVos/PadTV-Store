"""TV Store frontend; installs run asynchronously outside the rendering process."""
import json
import sys
from PyQt6.QtCore import QProcess
from padtv_store.catalog import load, SOURCES
from .apps import UserApp

class StoreMixin:
    def init_store(self):
        self.products = load()
        self.store_category = 'Vše'
        self.store_process = None
        self.store_callback = None
        self.store_native = None
        self.store_busy = ''

    def product_app(self, product):
        return UserApp(product.id, product.title, product.kind, product.target, product.symbol, product.color)

    def product_installed(self, product):
        if product.kind == 'web':
            return any(a.id == product.id and a.kind == 'web' and a.target == product.target
                       for a in self.library.list())
        return bool(self.store_native and product.target in self.store_native.get(product.kind, []))

    def store_items(self):
        return [p for p in self.products if self.store_category == 'Vše'
                or (self.store_category == 'Získané' and self.product_installed(p))
                or p.category == self.store_category]

    def select_store_category(self, name):
        self.store_category = name
        self.set_page('store')

    def store_detail(self, product):
        from .ui import ChoiceDialog
        if self.store_busy:
            self.toast('Probíhá správa aplikace. Počkejte na dokončení.')
            return
        message = product.description + '\n\nZdroj: ' + SOURCES[product.source]
        if product.compatibility:message+='\n\nKompatibilita: '+product.compatibility
        choices = [('Zpět', 0)]
        installed = self.product_installed(product)
        if product.kind == 'apt':
            message += '\nSoučást systému · aktualizuje se společně s PadTV.'
            if installed or self.preview:
                choices.append(('Otevřít', 3))
        elif product.installable:
            if product.kind == 'android' and not installed:
                if not product.compatibility:
                    message += '\nPadBridge: kompatibilita zatím není ověřená. Google Play používá Waydroid.'
                message += '\nInstalaci potvrdíte v Google Play po přihlášení. Dostupnost určuje Google Play podle zařízení.'
                if not self.store_native or not self.store_native.get('android_known'):
                    message += '\nStav instalace zatím není ověřený. Použijte Obnovit stav po spuštění Androidu.'
                choices += [('PadBridge', 6), ('Google Play', 1)]
                if not self.store_native or not self.store_native.get('google_play'):
                    choices += [('Připravit', 4)]
                choices += [('Obnovit', 5)]
            elif product.kind == 'flatpak' and self.store_native is None and not self.preview:
                message += '\nNačítá se stav instalace. Zkuste to za chvíli.'
            else:
                choices += [('Otevřít', 3), ('Odinstalovat', 2)] if installed else [('Získat', 1)]
        else:
            message += '\nZdroj ještě není připojený.'
        dialog = ChoiceDialog(self, product.title, message, choices)
        answer = dialog.exec()
        dialog.deleteLater()
        if answer in (1, 2):
            self.store_change(product, answer == 1)
        elif answer == 3:
            if product.kind == 'apt':
                self.launch({'system-browser': 'browser'}[product.id])
            else:
                self.launch_user(self.product_app(product))
        elif answer == 4:
            self.prepare_android(google_play=True)
        elif answer == 5:
            self.android_task('list', callback=lambda data: self.refresh_store())
        elif answer == 6:
            self.install_apk()

    def store_change(self, product, install):
        if self.store_process:
            self.toast('Počkejte na dokončení předchozí operace.')
            return
        if not product.installable:
            self.toast('Tento zdroj zatím není připojený.')
            return
        app = self.product_app(product)
        if not install and 'user:' + app.id in self.processes:
            self.toast('Před odinstalováním aplikaci zavřete.')
            return
        if product.kind == 'web':
            # Preview has its own library. Real web installs are Chromium profiles
            # and removable manifests, never privileged Debian packages.
            try:
                self.library.install(app) if install else self.library.remove(app, remove_data=True)
            except (OSError, ValueError) as error:
                self.toast(str(error))
                return
            self.set_page(self.page)
            self.toast(product.title + (' je přidané do aplikací.' if install else ' je odinstalované.'))
            return
        if self.preview:
            self.toast('Náhled · aplikace z Flathubu a Google Play se instalují v PadTV OS.')
            return
        self.store_busy = product.title
        def done(result):
            self.store_busy = ''
            if result.get('ok'):
                if product.kind == 'android' and install:
                    if result.get('opened'):
                        self.activate_application('android-shell', ['weston', '--socket=padtv-android'], wait=8)
                        self.toast('Otevřeno Google Play. Instalaci dokončete v obchodě.')
                    # Only inventory reconciliation may add an Android store app.
                    self.refresh_store()
                    return
                try:
                    self.library.install(app) if install else self.library.remove(app)
                except (OSError, ValueError) as error:
                    self.toast(str(error))
                else:
                    self.toast(product.title + (' je nainstalované.' if install else ' je odinstalované.'))
            else:
                self.toast(result.get('error', 'Operace se nezdařila.'))
            self.refresh_store()
        self.store_request('install' if install else 'remove', product.id, callback=done)
        self.toast(('Otevírá se Google Play · ' if product.kind == 'android' and install else 'Instaluje se ' if install else 'Odinstalovává se ') + product.title + '…')

    def refresh_store(self):
        if self.preview or self.store_process:
            return
        def done(result):
            if result.get('ok'):
                self.store_native = result
                # Reconcile external native installs/removals without faking state.
                for product in self.products:
                    if (product.kind == 'flatpak' and not result.get('error')
                            or product.kind == 'android' and result.get('android_known') and not result.get('android_error')):
                        app = self.product_app(product)
                        if product.kind == 'android':
                            # Older APK imports used other IDs, including "youtube".
                            # Normalize only Android manifests, keeping web profiles.
                            for saved in self.library.list():
                                if saved.kind == 'android' and saved.target == product.target and saved.id != product.id:
                                    self.library.remove(saved)
                        self.library.install(app) if self.product_installed(product) else self.library.remove(app)
                if result.get('error'):
                    self.toast(result['error'])
                if self.page in ('store', 'apps', 'manage', 'home'):
                    self.set_page(self.page, self.grid_page)
            else:
                self.toast(result.get('error', 'Stav aplikací se nepodařilo načíst.'))
        self.store_request('status', callback=done)

    def store_request(self, action, app_id=None, callback=None):
        if self.preview or self.store_process:
            return
        process = QProcess(self)
        self.store_process = process
        self.store_callback = callback
        process.setProgram(sys.executable)
        process.setArguments(['-m', 'padtv_store.cli', action] + ([app_id] if app_id else []))
        # Bound QObject receivers disconnect when the window is destroyed.
        # A closure here can run during child destruction and crash Qt on Linux.
        process.finished.connect(self.finish_store_request)
        process.errorOccurred.connect(self.store_process_error)
        process.start()

    def finish_store_request(self, *args):
        process = self.sender()
        if process is None or self.store_process is not process:
            return
        callback = self.store_callback
        self.store_process = self.store_callback = None
        try:
            result = json.loads(bytes(process.readAllStandardOutput()).decode())
        except (ValueError, UnicodeError):
            result = {'ok': False, 'error': 'Správce aplikací neodpověděl.'}
        process.deleteLater()
        if callback:
            callback(result)

    def store_process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.finish_store_request()

    def store_sources(self):
        from .ui import ChoiceDialog
        dialog = ChoiceDialog(self, 'Zdroje aplikací',
            'Web Apps · webové služby v samostatném okně\nFlathub · uživatelské linuxové aplikace\n'
            'PadBridge · místní podepsaná APK, experimentální kompatibilita\n'
            'Google Play · Android TV aplikace; vyžaduje Android s Google Play a přihlášení\n'
            'Debian APT · součásti systému\nGitHub · vlastní aplikace PadTV, zatím nepřipojeno\n'
            'PadTV Repository · komunitní aplikace, zatím nepřipojeno', [('Zpět', 0)])
        dialog.exec()
        dialog.deleteLater()

