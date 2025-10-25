# replay_system.py
import cv2
import numpy as np
from collections import deque
from threading import Thread, Lock
import time
import requests
import os
from datetime import datetime
import keyboard  # pip install keyboard
import json

class ReplayBufferSystem:
    def __init__(self, camera_sources, buffer_seconds=120, fps=30):
        """
        Sistema de Replay Buffer para múltiplas câmeras
        
        Args:
            camera_sources: dict {camera_id: camera_url_or_index}
                           Ex: {1: 0, 2: "rtsp://192.168.1.100/stream"}
            buffer_seconds: Segundos para manter no buffer (padrão: 120 = 2 minutos)
            fps: Frames por segundo da captura
        """
        self.camera_sources = camera_sources
        self.buffer_seconds = buffer_seconds
        self.fps = fps
        self.buffer_size = buffer_seconds * fps
        
        # Buffer circular para cada câmera (deque com tamanho máximo)
        self.frame_buffers = {}
        self.video_captures = {}
        self.locks = {}
        self.running = False
        self.threads = []
        
        # Configurações de upload
        self.upload_url = "http://seuservidor.com/upload.php"
        self.output_dir = "replay_clips"
        
        # Criar diretório de saída
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Inicializar buffers e capturas
        for cam_id, source in camera_sources.items():
            self.frame_buffers[cam_id] = deque(maxlen=self.buffer_size)
            self.locks[cam_id] = Lock()
            
            # Abrir captura de vídeo
            cap = cv2.VideoCapture(source)
            
            # Configurar resolução (ajuste conforme necessário)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            cap.set(cv2.CAP_PROP_FPS, fps)
            
            if not cap.isOpened():
                print(f"⚠️  Erro ao abrir câmera {cam_id}: {source}")
            else:
                print(f"✅ Câmera {cam_id} conectada: {source}")
                
            self.video_captures[cam_id] = cap
    
    def start(self):
        """Inicia a captura contínua em threads separadas"""
        self.running = True
        
        # Uma thread para cada câmera
        for cam_id in self.camera_sources.keys():
            cap = self.video_captures.get(cam_id)
            # Não iniciar thread se a captura não foi aberta corretamente
            if cap is None or not getattr(cap, 'isOpened', lambda: False)():
                print(f"⛔ Pulando câmera {cam_id} porque não está aberta.")
                continue

            thread = Thread(target=self._capture_loop, args=(cam_id,), daemon=True)
            thread.start()
            self.threads.append(thread)
            print(f"🎥 Thread de captura iniciada para câmera {cam_id}")
        
        print(f"\n✅ Sistema iniciado! Buffer de {self.buffer_seconds}s ({self.buffer_size} frames)")
        print("Pressione os botões configurados para salvar os clipes\n")
    
    def _capture_loop(self, cam_id):
        """Loop de captura contínua para uma câmera específica"""
        cap = self.video_captures[cam_id]
        
        while self.running:
            ret, frame = cap.read()
            
            if not ret:
                print(f"⚠️  Erro ao ler frame da câmera {cam_id}")
                time.sleep(0.1)
                continue
            
            # Adicionar timestamp ao frame (opcional, para debug)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            # Armazenar frame com timestamp no buffer circular
            with self.locks[cam_id]:
                self.frame_buffers[cam_id].append({
                    'frame': frame.copy(),
                    'timestamp': timestamp
                })
            
            # Controlar FPS (aguardar tempo entre frames)
            time.sleep(1.0 / self.fps)
    
    def save_replay(self, cam_id, extra_seconds_after=5):
        """
        Salva o conteúdo do buffer em arquivo de vídeo
        
        Args:
            cam_id: ID da câmera para salvar
            extra_seconds_after: Segundos extras para capturar após o botão
        """
        if cam_id not in self.frame_buffers:
            print(f"❌ Câmera {cam_id} não encontrada")
            return None
        
        print(f"\n🔴 REPLAY ACIONADO - Câmera {cam_id}")
        
        # Copiar buffer atual para não perder frames durante o salvamento
        with self.locks[cam_id]:
            buffer_copy = list(self.frame_buffers[cam_id])
        
        if len(buffer_copy) == 0:
            print(f"⚠️  Buffer vazio para câmera {cam_id}")
            return None
        
        # Capturar frames extras após o acionamento:
        # -> NÃO ler diretamente de VideoCapture aqui (evita condição de corrida com a thread de captura)
        # -> deixar a thread de captura popular o buffer e depois copiar os frames extras do buffer
        print(f"⏱️  Capturando {extra_seconds_after}s extras (via buffer)...")
        # Espera o tempo extra, permitindo que _capture_loop acrescente frames ao buffer
        wait_end = time.time() + extra_seconds_after
        while time.time() < wait_end:
            time.sleep(0.05)

        # Copiar novamente o buffer e extrair apenas os frames adicionados após a cópia inicial
        with self.locks[cam_id]:
            buffer_after = list(self.frame_buffers[cam_id])

        extra_frames = []
        try:
            last_ts = buffer_copy[-1]['timestamp']
            # Procurar índice do último timestamp da cópia anterior
            idx = next((i for i, f in enumerate(buffer_after) if f['timestamp'] == last_ts), None)
            if idx is None:
                # Se não encontrou (possível sobrescrita), pegar os últimos N frames como fallback
                num_extra = int(extra_seconds_after * self.fps)
                extra_frames = buffer_after[-num_extra:] if num_extra <= len(buffer_after) else buffer_after
            else:
                extra_frames = buffer_after[idx+1:]
        except Exception:
            num_extra = int(extra_seconds_after * self.fps)
            extra_frames = buffer_after[-num_extra:] if num_extra <= len(buffer_after) else buffer_after
        
        # Combinar buffer + frames extras
        all_frames = buffer_copy + extra_frames
        
        # Criar nome do arquivo
        filename = f"replay_cam{cam_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        filepath = os.path.join(self.output_dir, filename)
        
        # Salvar vídeo em thread separada (para não bloquear)
        thread = Thread(target=self._save_video_file, 
                       args=(all_frames, filepath, cam_id), 
                       daemon=True)
        thread.start()
        
        return filename
    
    def _save_video_file(self, frames, filepath, cam_id):
        """Salva frames em arquivo de vídeo e faz upload"""
        if len(frames) == 0:
            return
        
        print(f"💾 Salvando {len(frames)} frames ({len(frames)/self.fps:.1f}s)...")
        
        # Obter dimensões do primeiro frame
        height, width = frames[0]['frame'].shape[:2]
        
        # Codec e VideoWriter
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(filepath, fourcc, self.fps, (width, height))
        
        # Escrever todos os frames
        for frame_data in frames:
            out.write(frame_data['frame'])
        
        out.release()
        
        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"✅ Vídeo salvo: {filepath} ({file_size_mb:.2f} MB)")
        
        # Upload para servidor
        self._upload_to_server(filepath, cam_id)
    
    def _upload_to_server(self, filepath, cam_id):
        """Faz upload do vídeo para servidor via PHP"""
        try:
            print(f"📤 Fazendo upload para servidor...")
            
            with open(filepath, 'rb') as f:
                files = {'video': f}
                data = {
                    'camera_id': cam_id,
                    'timestamp': datetime.now().isoformat()
                }
                
                response = requests.post(
                    self.upload_url, 
                    files=files, 
                    data=data,
                    timeout=60
                )
                
                if response.status_code == 200:
                    print(f"✅ Upload concluído com sucesso!")
                    result = response.json()
                    print(f"🔗 URL: {result.get('url', 'N/A')}")
                else:
                    print(f"❌ Erro no upload: {response.status_code}")
                    
        except Exception as e:
            print(f"❌ Erro ao fazer upload: {str(e)}")
    
    def setup_keyboard_shortcuts(self):
        """Configura atalhos de teclado (para teste sem placa arcade)"""
        print("\n⌨️  Atalhos de teclado configurados:")
        for cam_id in self.camera_sources.keys():
            key = str(cam_id)
            print(f"   Tecla '{key}' -> Câmera {cam_id}")
            keyboard.add_hotkey(key, lambda c=cam_id: self.save_replay(c))
        
        print("   Tecla 'q' -> Sair")
        keyboard.add_hotkey('q', self.stop)
    
    def setup_arcade_buttons(self):
        """Configura botões da placa arcade USB"""
        import pygame
        
        pygame.init()
        pygame.joystick.init()
        
        if pygame.joystick.get_count() == 0:
            print("⚠️  Nenhuma placa arcade/joystick detectada")
            return
        
        joystick = pygame.joystick.Joystick(0)
        joystick.init()
        
        print(f"\n🕹️  Placa arcade conectada: {joystick.get_name()}")
        print(f"   Botões disponíveis: {joystick.get_numbuttons()}")
        
        # Mapeamento: botão físico -> câmera
        # Ajuste conforme sua configuração
        button_mapping = {
            0: 1,  # Botão 0 -> Câmera 1
            1: 2,  # Botão 1 -> Câmera 2
            2: 3,  # Botão 2 -> Câmera 3
        }
        
        def monitor_buttons():
            clock = pygame.time.Clock()
            while self.running:
                for event in pygame.event.get():
                    if event.type == pygame.JOYBUTTONDOWN:
                        button_id = event.button
                        if button_id in button_mapping:
                            cam_id = button_mapping[button_id]
                            print(f"\n🔘 Botão {button_id} pressionado!")
                            self.save_replay(cam_id)
                
                clock.tick(30)  # 30 FPS para monitoramento
        
        # Thread para monitorar botões
        thread = Thread(target=monitor_buttons, daemon=True)
        thread.start()
    
    def stop(self):
        """Para o sistema"""
        print("\n🛑 Parando sistema...")
        self.running = False
        
        # Liberar recursos
        for cap in self.video_captures.values():
            cap.release()
        
        cv2.destroyAllWindows()
        print("✅ Sistema encerrado")

# ============================================
# EXEMPLO DE USO
# ============================================

if __name__ == "__main__":
    # Configuração das câmeras
    # Para câmeras USB/webcam: use índice (0, 1, 2...)
    # Para câmeras IP: use URL RTSP
    
    cameras = {
        1: 0,  # Webcam integrada
        # 2: "rtsp://192.168.1.100:554/stream",  # Câmera IP 1
        # 3: "rtsp://192.168.1.101:554/stream",  # Câmera IP 2
    }
    
    # Criar sistema
    replay_system = ReplayBufferSystem(
        camera_sources=cameras,
        buffer_seconds=120,  # 2 minutos de buffer
        fps=30
    )
    
    # Iniciar captura
    replay_system.start()
    
    # Configurar controles
    # Opção 1: Teclado (para testes)
    replay_system.setup_keyboard_shortcuts()
    
    # Opção 2: Placa arcade (descomente para usar)
    # replay_system.setup_arcade_buttons()
    
    # Manter programa rodando
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        replay_system.stop()
