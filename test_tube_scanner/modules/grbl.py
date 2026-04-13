'''
GCode pour piloter la L2544 Laser Engraving Machine

    GRBLController:
        Commande uniquement les mouvements (X, Y)
        Le mode absolue est retenu

    GridScanner
        Balayage complet de la grille d'éprouvettes en mode serpentin

    Usage:
        grbl = GRBLController()
        scan = GridScanner(grbl, xbase=100, ybase=100, duration=5)
        scan.start()

Created on 25 mars 2026

@author: denis@miraceti.net
'''
import logging
import serial
import time
import threading
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GRBLController:
    '''
    Contrôleur pour machine de gravure laser L2544 (GRBL 1.1f)
    Fonctions de base pour la calibration : déplacement manuel et gestion de la position.
    '''
    X_MAX = 350
    Y_MAX = 250
    X_MIN = 0
    Y_MIN = 0

    def __init__(self, port='/dev/ttyUSB0', baudrate=115200, timeout=1, send_callback=None, x_max=None, y_max=None):
        self.lock = threading.Lock()
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

        if x_max is not None:
            self.X_MAX = x_max
        if y_max is not None:
            self.Y_MAX = y_max

        self._state = send_callback
        if self._state is None:
            self._state = self._send_msg

        self.x, self.y = 0, 0
        self.start_connection()
        self._wake_up()
        self._init_machine()

    def wait_for(self, delay=1.0):
        threading.Event().wait(delay*1.0)

    def _send_msg(self, **msg):
        print(msg)

    def clear_buffer(self):
        while self.ser.in_waiting >0:
            msg = self.ser.readline().decode().strip()
            print(f"Buffer: {msg}")
            self._state(state='serial', msg=msg)

    def start_connection(self):
        n = 0
        while True:
            try:
                self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout, exclusive=True)
                # CRITIQUE :
                self.ser.setDTR(False)
                self.ser.setRTS(False)
                self.clear_buffer()
                break
            except Exception as e:
                print(f"Erreur de connexion (essai {n}): {e}")
                n += 1
                self.wait_for(1.0)

    def _init_machine(self):
        self.send("G21")  # Unités en mm
        self.send("G90")  # Mode absolu

    def _clamp(self, x, y):
        self.clear_buffer()
        x = max(self.X_MIN, min(self.X_MAX, x))
        y = max(self.Y_MIN, min(self.Y_MAX, y))
        return x, y

    def _wake_up(self):
        #with self.lock:
        self.ser.write(b"\r\n\r\n")
        self.wait_for(1)
        self.clear_buffer()


    def send(self, cmd, wait_ok=True, timeout=5):
        try:
            return self._send(cmd, wait_ok, timeout)
        except Exception as e:
            #print("Send error:", e)
            self._state(state='error', msg=f"Error send {cmd} command: {e}")
            self.close()
            self.start_connection()
            self._wake_up()
            self._init_machine()
            '''
            self.recover()
            self.reset_grbl()
            raise'''

    def recover(self):
        #print("Récupération de GRBL...")
        self._state(state='recover', msg=f"Erreur, récupération de GRBL...")
        self.wait_for(1)
        self._wake_up()

    def _send(self, cmd, wait_ok=True, timeout=5):
        #print(f">>> {cmd}")
        self._state(state='send', msg=f">>> {cmd}")
        self.ser.write((cmd + "\n").encode())

        if not wait_ok:
            return None

        start = time.time()
        while True:
            if time.time() - start > timeout:
                raise TimeoutError(f"Timeout sur la commande: {cmd}")

            raw = self.ser.readline()
            if not raw:
                continue

            line = raw.decode(errors="ignore").strip()
            if not line:
                continue
            if line.startswith("<"):
                continue  # Ignorer les messages de status asynchrones
            if "ok" in line.lower():
                return line
            if "error" in line.lower():
                raise Exception(f"Erreur GRBL: {line}")

    def get_status(self):
        #with self.lock:
        self.ser.write(b"?\n")
        while True:
            line = self.ser.readline()
            if not line:
                continue
            line = line.decode().strip()
            if line.startswith("<"):
                return line

    def reset_grbl(self):
        self.send("$X")  # Réinitialise les alarmes
        self.wait_idle()
        self.send("$H")  # Homing
        self.wait_idle()

    def _mpos(self, status):
        if "MPos" in status:
            mpos = status.split("MPos:")[1].split("|")[0]
            x, y, *_ = mpos.split(",")
            return float(x), float(y)
        return None, None

    def get_mpos(self):
        return self._mpos(self.get_status())

    def wait_idle(self, timeout=10):
        start = time.time()
        while True:
            if time.time() - start > timeout:
                raise TimeoutError("Délai d'attente pour Idle dépassé")
            status = self.get_status()
            self.x, self.y = self._mpos(status)
            self._state(xy=True, x=self.x, y=self.y)
            if status and "Idle" in status:
                break
            self.wait_for(0.1)

    def move_to(self, x, y, feed=1000):
        x, y = self._clamp(x, y)
        #cmd = f"G0 X{x:.2f} Y{y:.2f} F{feed}"     # feed is not updated in G0 mode
        cmd = f"G53 G1 X{x:.2f} Y{y:.2f} F{feed}"
        self.send(cmd)
        self.wait_idle()

    def move_relative_(self, dx=0, dy=0, feed=1000):
        self.send("G91")  # Mode relatif
        cmd = f"G0 X{dx} Y{dy} F{feed}"
        self.send(cmd)
        self.send("G90")  # Retour en mode absolu
        self.wait_idle()

    def move_relative(self, dx=0, dy=0, feed=1000):
        x, y = self.get_mpos()  # Position actuelle
        self.move_to(x + dx, y + dy)

    def go_origin(self, feed=1000):
        self.move_to(0, 0, feed=feed)
        self.wait_for(2.0)

    def set_position(self, x, y):
        x, y = self._clamp(x, y)
        cmd = f"G92 X{x:.2f} Y{y:.2f}"
        self.send(cmd)
        self.wait_for(2.0)

    def move_up(self, step=10, feed=1000):
        self.move_relative(dy=step, feed=feed)

    def move_down(self, step=10, feed=1000):
        self.move_relative(dy=-step, feed=feed)

    def move_left(self, step=10, feed=1000):
        self.move_relative(dx=-step, feed=feed)

    def move_right(self, step=10, feed=1000):
        self.move_relative(dx=step, feed=feed)

    def close(self):
        self.ser.close()


class GridScanner:

    def __init__(self, grbl, proc=None, **config):
        '''
            xbase        # Position X de départ (col 0) en mm
            ybase        # Position Y de départ (row 0) en mm
            cols         # Nombre de colonnes
            rows         # Nombre de lignes
            dx           # Pas entre colonnes en mm
            dy           # Pas entre lignes en mm
            duration     # Durée de filmage par éprouvette en secondes
            feed         # Vitesse de déplacement entre éprouvettes (mm/min)
        '''
        self.grbl = grbl
        self.proc = proc

        self.position = config.get('position', 'HG')
        self.xbase = config.get('xbase', 50)
        self.ybase = config.get('ybase', 50)
        self.cols = config.get('cols', 6)
        self.rows = config.get('rows', 4)
        self.dx = config.get('dx', 20)
        self.dy = config.get('dy', 19)
        self.feed = config.get('feed', 1000)
        self.duration = config.get('duration', 120) # secondes
        self.xnext = config.get('xnext', 50)
        self.ynext = config.get('ynext', 50)

        row_to_char = config.get('row_to_char', 'D,C,B,A')
        self.row_to_char = row_to_char.split(',')
        self.stop_playing = None


    def halt(self):
        self.proc.record = False
        return self.stop_playing.set()

    def _capture(self, uuid: str, duration: float, stop_running: Optional[threading.Event]) -> None:
        """
        Déclenche la caméra ArduCam et attend la fin de l'acquisition.
        """
        print(f"# démarrer l'enregistrement {uuid}")
        self.proc.uuid = uuid
        self.proc.record = True

        start = time.monotonic()
        while not stop_running.is_set():
            if time.monotonic() - start > duration:
                break
            self.grbl.wait_for(1.0)

        print("# arrêter l'enregistrement")
        self.proc.record = False
        self.proc.uuid = None

    def start(self, xnext=None, ynext=None, position=None):
        """
        Balayage complet de la grille d'éprouvettes en mode serpentin.

        Parcours :
          - Lignes paires  (0, 2)    : gauche → droite (col 0 → col 5)
          - Lignes impaires (1, 3)   : droite → gauche  (col 5 → col 0)

        Le déplacement entre éprouvettes se fait en mode absolu via move_to().
        La caméra filme pendant `` secondes sur chaque position.

        Grille : 6 colonnes × 4 lignes = 24 éprouvettes
          - x = XBASE + col * PAS_X
          - y = YBASE + row * PAS_Y
        """
        try:
            if xnext is None:
                xnext = self.xnext
            if ynext is None:
                ynext = self.ynext
            if position is None:
                position = self.position

            max_cells = self.cols * self.rows
            cell = 0

            logger.info("Début du scan serpentin : %d éprouvettes, %d s/éprouvette, durée totale estimée : %d min",
                max_cells,
                self.duration,
                (max_cells * self.duration) // 60,
            )

            self.stop_playing = threading.Event()
            for row in range(self.rows):
                if self.stop_playing.is_set():
                    break

                # Ordre des colonnes selon la parité de la ligne (serpentin)
                if row % 2 == 0:
                    # Ligne paire : gauche → droite
                    cols = range(self.cols)
                else:
                    # Ligne impaire : droite → gauche
                    cols = range(self.cols - 1, -1, -1)

                for col in cols:
                    if self.stop_playing.is_set():
                        break
                    # Calcul de la position absolue en mm
                    x = self.xbase + col * self.dx
                    y = self.ybase + row * self.dy
                    cell += 1
                    logger.info(
                        "[%02d/%02d] row=%d col=%d  →  X=%.1f mm  Y=%.1f mm",
                        cell, max_cells, row, col, x, y,
                    )
                    self.grbl.move_to(x, y, feed=self.feed)

                    uuid = f'{self.proc.session}-{position}-{self.row_to_char[row]}{col+1}'
                    self._capture(uuid, self.duration, self.stop_playing)

            # Retour à nexr après le scan
            logger.info("Scan terminé — retour à l'origine (X=%.1f  Y=%.1f)", xnext, ynext)
            self.grbl.move_to(xnext, ynext, feed=self.feed*2)
        except Exception as e:
            logger.error(f"scan error: {e}")

