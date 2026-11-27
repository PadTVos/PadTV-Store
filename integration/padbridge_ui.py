"""Asynchronous PadBridge adapter. Waydroid data and manifests remain separate."""
import json
import os
from pathlib import Path
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QFileDialog
from .apps import UserApp, PACKAGE

def bridge_root():
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'padbridge'

def bridge_app(meta):
    package=meta['package'];digest=meta.get('installation_id') or meta['sha256']
    if not PACKAGE.fullmatch(package) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Neplatná metadata PadBridge.')
    icon=bridge_root()/'packages'/package/digest/'icon'
    return UserApp('padbridge.'+package,meta['title'],'padbridge',package,
                   icon_path=str(icon) if meta.get('icon') else '')

class PadBridgeMixin:
    def bridge_request(self,action,*args,callback=None):
        if self.preview:
            self.toast('Náhled Windows · PadBridge spouští APK pouze v PadTV OS.')
            return
        if getattr(self,'bridge_process',None):
            self.toast('Počkejte na dokončení operace PadBridge.')
            return
        process=QProcess(self);self.bridge_process=process;self.bridge_callback=callback
        process.setProgram('padbridge');process.setArguments([action,*args])
        process.finished.connect(self.finish_bridge_request)
        process.errorOccurred.connect(self.bridge_request_error)
        process.start()

    def finish_bridge_request(self,*args):
        process=self.sender()
        if process is None or getattr(self,'bridge_process',None) is not process:return
        callback=self.bridge_callback;self.bridge_process=None;self.bridge_callback=None
        try:
            data=json.loads(bytes(process.readAllStandardOutput()).decode('utf-8'))
            if not data.get('ok'):raise ValueError(data.get('error','Operace PadBridge se nezdařila.'))
        except (ValueError,UnicodeError) as error:
            self.toast(str(error)[:1200])
        else:
            if callback:callback(data)
        process.deleteLater()

    def bridge_request_error(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            self.finish_bridge_request()
            self.toast('PadBridge není nainstalovaný nebo jej nelze spustit.')

    def install_apk(self,path=None):
        from .ui import ChoiceDialog
        if self.preview:
            self.toast('Instalace APK je dostupná v PadTV OS. Náhled Windows Android nespouští.')
            return
        if not isinstance(path,str):
            dialog=ChoiceDialog(self,'Android runtime','PadBridge je preferovaný experimentální runtime. Waydroid používá samostatné prostředí a samostatná data.',[('Zpět',0),('PadBridge 0.4',1),('Waydroid · záloha',2)])
            runtime=dialog.exec();dialog.deleteLater()
            if runtime==2:self.install_waydroid_apk();return
            if runtime!=1:return
            paths,_=QFileDialog.getOpenFileNames(self,'Instalovat APK / sadu split APK',str(Path.home()),'Android aplikace (*.apk *.apks *.apkm)')
        else:paths=[path]
        if not paths:return
        def inspected(result):
            meta=result['app'];diagnostic=result['diagnostics']
            message=f"{meta['title']}\n{meta['package']} · {meta['version_name']}\nPodpis SHA-256: {meta['signers'][0]}\n\nPadBridge je experimentální."
            if not diagnostic['eligible_for_trial']:
                message+='\nNalezené překážky kompatibility: '+', '.join(diagnostic['unsupported_classes'][:6])
                if diagnostic['native_libraries']:message+='\nKompatibilitu jednotlivých nativních knihoven uvádí diagnostika APK.'
                message+='\n'+'\n'.join(diagnostic['dex_errors'])
            message+='\nPožadovaná oprávnění: '+(', '.join(meta['permissions']) or 'žádná')
            message+=f"\nDEX: {diagnostic['dex_files']} · split APK: {len(meta.get('splits',[]))}"
            message+='\nSíť je ve výchozím stavu zakázaná; povolíte ji ve správě aplikace.'
            dialog=ChoiceDialog(self,'Instalovat APK',message,[('Zpět',0),('Instalovat',1)])
            answer=dialog.exec();dialog.deleteLater()
            if answer:self.bridge_request('install-set',*paths,callback=installed)
        def installed(result):
            app=bridge_app(result['app']);self.library.install(app);self.set_page('apps')
            self.toast(app.title+' je nainstalovaná přes PadBridge. Kompatibilita je experimentální.')
        self.bridge_request('inspect-set',*paths,callback=inspected)

    def install_bridge_demo(self):
        self.install_apk('/usr/share/padbridge/examples/basic.apk')

    def refresh_bridge(self):
        def loaded(result):
            apps=[bridge_app(meta) for meta in result['apps']]
            for app in apps:self.library.install(app)
            for old in self.library.list():
                if old.kind=='padbridge' and not any(a.id==old.id for a in apps):self.library.remove(old)
            self.set_page(self.page)
        self.bridge_request('list',callback=loaded)

    def bridge_details(self,app):
        from .ui import ChoiceDialog
        def loaded(result):
            internet='android.permission.INTERNET' in result['granted']
            message='PadBridge · experimentální Android runtime\nSoukromá data této aplikace jsou oddělená.\nSíť: '+('povolená' if internet else 'zakázaná')
            message+='\nPožadovaná oprávnění: '+(', '.join(result['requested']) or 'žádná')
            choices=[('Zpět',0),('Spustit',1),('Odinstalovat',2),('Diagnostika',4)]
            if 'android.permission.INTERNET' in result['requested']:choices.append(('Zakázat síť' if internet else 'Povolit síť',3))
            dialog=ChoiceDialog(self,app.title,message,choices);answer=dialog.exec();dialog.deleteLater()
            if answer==1:self.launch_user(app)
            elif answer==2:
                dialog=ChoiceDialog(self,'Odinstalovat '+app.title,'Co udělat s daty aplikace?',[('Zpět',0),('Zachovat data',1),('Smazat i data',2)])
                choice=dialog.exec();dialog.deleteLater()
                if choice:
                    def removed(data):self.library.remove(app);self.set_page(self.page);self.toast(app.title+' je odinstalovaná.')
                    self.bridge_request('remove',app.target,*(['--delete-data'] if choice==2 else []),callback=removed)
            elif answer==3:self.bridge_request('permissions',app.target,json.dumps([] if internet else ['android.permission.INTERNET']),callback=lambda _:self.bridge_details(app))
            elif answer==4:self.bridge_diagnostics(app)
        self.bridge_request('permissions',app.target,callback=loaded)

    def bridge_diagnostics(self,app):
        from .ui import ChoiceDialog
        def loaded(result):
            diagnostic=result['diagnostics'];message='PadBridge 0.4 · Enjarify / OpenJDK\n'
            message+='Statická analýza nenahrazuje ověření skutečným spuštěním.\n'
            message+='Chybějící API: '+(', '.join(diagnostic['unsupported_classes'][:25]) or 'nenalezené podle názvů tříd')
            message+='\nNativní knihovny: '+(', '.join(diagnostic['native_libraries'][:12]) or 'žádné')
            message+='\nDEX: '+(', '.join(diagnostic.get('dex_versions',[])))
            message+='\n'+diagnostic['drm']
            if result.get('last_error'):message+='\n\nPoslední běh:\n'+result['last_error'][-1800:]
            dialog=ChoiceDialog(self,app.title+' · diagnostika',message,[('Zpět',0)]);dialog.exec();dialog.deleteLater()
        self.bridge_request('diagnose-installed',app.target,callback=loaded)
