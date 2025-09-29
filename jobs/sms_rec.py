import subprocess
import logging
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

log = logging.getLogger(__name__)


class SmsReceiver:
    def __init__(self):
        self.modem_id = self._get_modem_id()
        if self.modem_id is None:
            raise ValueError("Модем не найден. Проверьте подключение и ModemManager")
        log.info(f"Используем модем ID: {self.modem_id}")

    def _get_modem_id(self):
        try:
            output = subprocess.run(['mmcli', '-L'], capture_output=True, text=True, check=True).stdout
            match = re.search(r'/org/freedesktop/ModemManager1/Modem/(\d+)', output)
            if match:
                return int(match.group(1))
            else:
                log.info('Модем не найден в выводе mmcli -L')
                return None

        except subprocess.CalledProcessError as e:
            log.error(f"Ошибка выполнения mmcli -L: {e.stderr}")
            return None

    def _run_mmcli(self, args):
        cmd = ['mmcli', '-m', str(self.modem_id)] + args
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            log.error(f"Ошибка выполнения команды: {e.stderr}")
            return None

    def list_sms(self, only_received=True):
        output = self._run_mmcli(['--messaging-list-sms'])
        if not output:
            return []

        lines = output.strip().split('\n')
        sms_ids = []
        for line in lines:

            match = re.search(r'/org/freedesktop/ModemManager1/SMS/(\d+)\s+\((received|sent)\)', line)
            if not match:
                continue
            sms_id = int(match.group(1))
            state = match.group(2)
            if not only_received or state == 'received':
                sms_ids.append(sms_id)
        return sms_ids

    def read_sms(self, sms_id):
        output = self._run_mmcli(['-s', str(sms_id)])
        if not output:
            return None

        sms_data = {}
        number_match = re.search(r'number:\s*\'?([^\']+?)(?=\n|$)', output)
        text_match = re.search(r'text:\s*\'?([^\']+?)(?=\n|$)', output)

        sms_data['number'] = number_match.group(1).strip() if number_match else 'Unknown'
        sms_data['text'] = text_match.group(1).strip() if text_match else 'No text'

        return sms_data

    def delete_sms(self, sms_id):
        output = self._run_mmcli([f'--messaging-delete-sms={sms_id}'])
        if output and 'successfully deleted' in output.lower():
            log.info(f"SMS {sms_id} удаленно успешно")
        else:
            log.error(f"Ошибка удаления SMS {sms_id}: {output}")
