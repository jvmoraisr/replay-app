<?php
// upload.php - Script para receber vídeos do sistema Python

header('Content-Type: application/json');

// Configurações
$upload_dir = 'replays/';
$max_file_size = 500 * 1024 * 1024; // 500 MB
$allowed_extensions = ['mp4', 'avi', 'mov'];

// Criar diretório se não existir
if (!is_dir($upload_dir)) {
    mkdir($upload_dir, 0755, true);
}

// Verificar se é requisição POST
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['error' => 'Método não permitido']);
    exit;
}

// Verificar se arquivo foi enviado
if (!isset($_FILES['video'])) {
    http_response_code(400);
    echo json_encode(['error' => 'Nenhum arquivo enviado']);
    exit;
}

$file = $_FILES['video'];
$camera_id = isset($_POST['camera_id']) ? intval($_POST['camera_id']) : 0;
$timestamp = isset($_POST['timestamp']) ? $_POST['timestamp'] : date('Y-m-d H:i:s');

// Verificar erros no upload
if ($file['error'] !== UPLOAD_ERR_OK) {
    http_response_code(500);
    echo json_encode(['error' => 'Erro no upload: ' . $file['error']]);
    exit;
}

// Verificar tamanho do arquivo
if ($file['size'] > $max_file_size) {
    http_response_code(413);
    echo json_encode(['error' => 'Arquivo muito grande']);
    exit;
}

// Verificar extensão
$file_extension = strtolower(pathinfo($file['name'], PATHINFO_EXTENSION));
if (!in_array($file_extension, $allowed_extensions)) {
    http_response_code(400);
    echo json_encode(['error' => 'Extensão não permitida']);
    exit;
}

// Gerar nome único para o arquivo
$unique_id = uniqid('replay_', true);
$new_filename = sprintf(
    'cam%d_%s_%s.%s',
    $camera_id,
    date('Ymd_His'),
    $unique_id,
    $file_extension
);

// Criar subdiretório por data
$date_dir = $upload_dir . date('Y-m-d') . '/';
if (!is_dir($date_dir)) {
    mkdir($date_dir, 0755, true);
}

$destination = $date_dir . $new_filename;

// Mover arquivo
if (move_uploaded_file($file['tmp_name'], $destination)) {
    // Salvar metadados em JSON
    $metadata = [
        'camera_id' => $camera_id,
        'timestamp' => $timestamp,
        'upload_time' => date('Y-m-d H:i:s'),
        'filename' => $new_filename,
        'file_size' => $file['size'],
        'file_path' => $destination
    ];
    
    $metadata_file = $date_dir . $unique_id . '_metadata.json';
    file_put_contents($metadata_file, json_encode($metadata, JSON_PRETTY_PRINT));
    
    // URL para acessar o vídeo
    $video_url = 'https://' . $_SERVER['HTTP_HOST'] . '/' . $destination;
    
    // Resposta de sucesso
    http_response_code(200);
    echo json_encode([
        'success' => true,
        'filename' => $new_filename,
        'url' => $video_url,
        'size' => $file['size'],
        'id' => $unique_id
    ]);
    
    // Log
    error_log("Replay salvo: $new_filename (Camera $camera_id)");
    
} else {
    http_response_code(500);
    echo json_encode(['error' => 'Erro ao salvar arquivo']);
}
?>
