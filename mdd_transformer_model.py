# Mount Google Drive
from google.colab import drive
drive.mount('/content/drive')

!pip install tensorflow-addons

!pip install antropy

!pip install mne
!pip install tensorflow

# Install required packages

# Uncomment if needed:
# !pip install antropy

# Import necessary libraries
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

import mne

from sklearn.model_selection import train_test_split, KFold
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score, roc_auc_score
from sklearn.utils import class_weight
from tensorflow.keras.utils import to_categorical
from tensorflow.keras import layers, models, regularizers
import tensorflow as tf

np.random.seed(42)
tf.random.set_seed(42)

# Set directories
data_directory = '/content/drive/My Drive/MDD-dataset'  # Update with your path
output_directory = '/content/drive/My Drive/output'
os.makedirs(output_directory, exist_ok=True)

import torch
torch.cuda.empty_cache()

# Check for CUDA availability.
import torch
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

# Import additional libraries for feature extraction
from scipy.signal import welch
from scipy.stats import skew, kurtosis
from antropy import sample_entropy

# Define feature extraction function
def extract_features(raw_data, sfreq):
    channel_features = []
    bands = {
        'delta': (0.5, 4),
        'theta': (4, 8),
        'alpha': (8, 12),
        'beta': (12, 30),
        'gamma': (30, 45)
    }
    for channel_data in raw_data:
        features = []
        # Time-domain features
        mean_val = np.mean(channel_data)
        std_val = np.std(channel_data)
        skew_val = skew(channel_data)
        kurt_val = kurtosis(channel_data)
        entropy_val = sample_entropy(channel_data)
        features.extend([mean_val, std_val, skew_val, kurt_val, entropy_val])
        # Frequency-domain features
        freqs, psd = welch(channel_data, sfreq, nperseg=1024)
        for band, (low, high) in bands.items():
            freq_ix = np.logical_and(freqs >= low, freqs <= high)
            band_power = np.trapz(psd[freq_ix], freqs[freq_ix])
            features.append(band_power)
        channel_features.append(features)
    return np.array(channel_features)  # Shape: (channels, features_per_channel)

# Define data segmentation function
def segment_data(data, window_size, overlap):
    n_channels, n_samples = data.shape
    step = window_size - overlap
    segments = []
    for start in range(0, n_samples - window_size + 1, step):
        end = start + window_size
        segment = data[:, start:end]
        segments.append(segment)
    return segments  # List of segments, each segment is of shape (channels, window_size)

# Load and preprocess EEG data
H_num = 30
MDD_num = 34
features_list = []
labels_list = []
categories = ['H', 'MDD']
eye_states = ['EC', 'EO', 'TASK']  # Include TASK data
sfreq = 256

# Parameters for windowing
window_size_seconds = 2  # 2-second windows
overlap_seconds = 1      # 1-second overlap
window_size = sfreq * window_size_seconds
overlap = sfreq * overlap_seconds

features_file = f"{data_directory}/Features_windowed.npy"
labels_file = f"{data_directory}/Labels_windowed.npy"

if not os.path.exists(features_file) or not os.path.exists(labels_file):
    print("Extracting features from EEG data...")
    for category in categories:
        label = 0 if category == 'H' else 1
        num_subjects = H_num if category == 'H' else MDD_num
        for i in range(1, num_subjects + 1):
            for state in eye_states:
                file_path = f"{data_directory}/{category} S{i} {state}.edf"
                if os.path.exists(file_path):
                    try:
                        raw = mne.io.read_raw_edf(file_path, preload=True, verbose=False)
                        data = raw.get_data()
                        n_channels, n_samples = data.shape
                        if n_channels > 19:
                            data = data[:19, :]
                        elif n_channels < 19:
                            print(f"File {file_path} has {n_channels} channels. Skipping.")
                            continue
                        required_samples = sfreq * 60
                        if n_samples < required_samples:
                            print(f"File {file_path} has insufficient length ({n_samples} samples). Skipping.")
                            continue
                        trimmed_data = data[:, :required_samples]
                        # Segment the data
                        segments = segment_data(trimmed_data, window_size, overlap)
                        for segment in segments:
                            features = extract_features(segment, sfreq)
                            # Flatten features per sample
                            features_flat = features.flatten()
                            features_list.append(features_flat)
                            labels_list.append(label)
                    except Exception as e:
                        print(f"Error processing {file_path}: {e}")
                else:
                    print(f"File not found: {file_path}")
    features_array = np.array(features_list)  # Shape: (samples, total_features)
    labels_array = np.array(labels_list)
    np.save(features_file, features_array)
    np.save(labels_file, labels_array)
    print("Feature extraction completed and saved.")
else:
    print("Features and labels already extracted. Loading from files.")
    features_array = np.load(features_file)
    labels_array = np.load(labels_file)

# Verify the shapes
print(f"Features shape: {features_array.shape}")
print(f"Labels shape: {labels_array.shape}")

# Reshape features_array
num_samples = features_array.shape[0]
num_channels = 19
num_features_per_channel = 10  # After adding entropy and all frequency bands

features_array = features_array.reshape(num_samples, num_channels, num_features_per_channel)
print(f"Features shape after reshaping: {features_array.shape}")  # Should be (samples, channels, features_per_channel)

# Now you can unpack the shape
num_samples, num_channels, num_features = features_array.shape

# Feature scaling
features_flat = features_array.reshape(num_samples, num_channels * num_features)
scaler = StandardScaler()
features_scaled = scaler.fit_transform(features_flat)
features_scaled = features_scaled.reshape(num_samples, num_channels, num_features)

# Prepare labels
num_classes = 2
labels_categorical = to_categorical(labels_array, num_classes)

# Split data
X_train_full, X_test, y_train_full, y_test = train_test_split(
    features_scaled, labels_categorical, test_size=0.2, random_state=42, stratify=labels_array
)

print(f"Training set size: {X_train_full.shape[0]} samples")
print(f"Testing set size: {X_test.shape[0]} samples")

# Calculate class weights
class_weights = class_weight.compute_class_weight(
    class_weight='balanced',
    classes=np.unique(labels_array),
    y=labels_array
)

class_weights = dict(enumerate(class_weights))

# Define custom positional encoding layer
@tf.keras.utils.register_keras_serializable()
class PositionalEncodingLayer(layers.Layer):
    def __init__(self, sequence_length, d_model, **kwargs):
        super(PositionalEncodingLayer, self).__init__(**kwargs)
        self.position_embeddings = layers.Embedding(input_dim=sequence_length, output_dim=d_model)
        self.sequence_length = sequence_length
        self.d_model = d_model

    def call(self, x):
        positions = tf.range(start=0, limit=self.sequence_length, delta=1)
        positions = self.position_embeddings(positions)
        positions = tf.expand_dims(positions, axis=0)  # Shape: (1, sequence_length, d_model)
        positions = tf.tile(positions, [tf.shape(x)[0], 1, 1])  # Broadcast to batch size
        return x + positions

    def get_config(self):
        config = super(PositionalEncodingLayer, self).get_config()
        config.update({
            'sequence_length': self.sequence_length,
            'd_model': self.d_model,
        })
        return config

# Define Transformer model without Batch Normalization and increased capacity
def build_transformer_model(input_shape, num_classes):
    inputs = layers.Input(shape=input_shape)
    sequence_length = input_shape[0]
    d_model = input_shape[1]

    x = PositionalEncodingLayer(sequence_length, d_model)(inputs)

    for _ in range(4):  # Increased from 3 to 4 encoder layers
        # Multi-head attention
        attention_output = layers.MultiHeadAttention(
            num_heads=8, key_dim=d_model, dropout=0.1
        )(x, x)
        attention_output = layers.Dropout(0.1)(attention_output)
        attention_output = layers.LayerNormalization(epsilon=1e-6)(attention_output)

        # Feed-forward network with L2 regularization and LeakyReLU activation
        ffn_output = layers.Dense(512, kernel_regularizer=regularizers.l2(1e-5))(attention_output)
        ffn_output = layers.LeakyReLU(alpha=0.01)(ffn_output)
        ffn_output = layers.Dropout(0.1)(ffn_output)
        ffn_output = layers.Dense(d_model, kernel_regularizer=regularizers.l2(1e-5))(ffn_output)
        ffn_output = layers.LayerNormalization(epsilon=1e-6)(ffn_output)

        # Skip connection
        x = layers.Add()([attention_output, ffn_output])

    # Global Average Pooling
    x = layers.GlobalAveragePooling1D()(x)

    # Output Layer
    outputs = layers.Dense(num_classes, activation='softmax')(x)

    model = models.Model(inputs=inputs, outputs=outputs)

    # Compile the model with a higher learning rate
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss='categorical_crossentropy',
        metrics=['accuracy']
    )

    return model

# Assuming X_train_full and num_classes are defined
input_shape = X_train_full.shape[1:]
print(f"Input shape: {input_shape}")
model = build_transformer_model(input_shape, num_classes)
model.summary()

# Callbacks
early_stopping = tf.keras.callbacks.EarlyStopping(
    monitor='val_loss', patience=300, restore_best_weights=True
)
model_checkpoint = tf.keras.callbacks.ModelCheckpoint(
    filepath=os.path.join(output_directory, 'best_transformer_model.keras'),
    monitor='val_loss',
    save_best_only=True
)
lr_scheduler = tf.keras.callbacks.ReduceLROnPlateau(
    monitor='val_loss', factor=0.5, patience=6, min_lr=1e-6
)
callbacks = [early_stopping, model_checkpoint, lr_scheduler]

# Implement K-Fold Cross-Validation
num_folds = 5
kfold = KFold(n_splits=num_folds, shuffle=True, random_state=42)

acc_per_fold = []
loss_per_fold = []
fold_no = 1

for train_index, val_index in kfold.split(X_train_full):
    print(f"\nTraining for fold {fold_no} ...")

    # Split data
    X_train, X_val = X_train_full[train_index], X_train_full[val_index]
    y_train, y_val = y_train_full[train_index], y_train_full[val_index]

    # Build model
    model = build_transformer_model(input_shape, num_classes)

    # Train the model
    history = model.fit(
        X_train, y_train,
        batch_size=32,
        epochs=300,
        validation_data=(X_val, y_val),
        callbacks=callbacks,
        verbose=1,
        class_weight=class_weights
    )

    # Load the best model saved during training
    model = tf.keras.models.load_model(os.path.join(output_directory, 'best_transformer_model.keras'))

    # Evaluate the model
    scores = model.evaluate(X_test, y_test, verbose=0)
    print(f'Score for fold {fold_no}: {model.metrics_names[0]} of {scores[0]:.4f}, {model.metrics_names[1]} of {scores[1]*100:.2f}%')
    acc_per_fold.append(scores[1] * 100)
    loss_per_fold.append(scores[0])

    fold_no += 1

# Display average scores
print('\nAverage scores for all folds:')
print(f'> Accuracy: {np.mean(acc_per_fold):.2f}% (+- {np.std(acc_per_fold):.2f}%)')
print(f'> Loss: {np.mean(loss_per_fold):.4f}')

# Evaluate on test set with the last model trained
test_loss, test_accuracy = model.evaluate(X_test, y_test, verbose=1)
print(f"\nTest Accuracy: {test_accuracy * 100:.2f}%")

# Classification report and confusion matrix
y_pred_probs = model.predict(X_test)
y_pred_classes = np.argmax(y_pred_probs, axis=1)
y_true = np.argmax(y_test, axis=1)
report = classification_report(y_true, y_pred_classes, target_names=['Healthy', 'MDD'])
print("Classification Report:")
print(report)
cm = confusion_matrix(y_true, y_pred_classes)
print("Confusion Matrix:")
print(cm)
plt.figure(figsize=(6,5))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=['Healthy', 'MDD'], yticklabels=['Healthy', 'MDD'])
plt.xlabel('Predicted')
plt.ylabel('True')
plt.title('Confusion Matrix')
plt.show()

# Plot training history for the last fold
def plot_training_history(history):
    fig, axs = plt.subplots(1, 2, figsize=(12, 4))
    # Accuracy plot
    axs[0].plot(history.history['accuracy'], label='Train Accuracy')
    axs[0].plot(history.history['val_accuracy'], label='Validation Accuracy')
    axs[0].set_title('Model Accuracy')
    axs[0].set_xlabel('Epoch')
    axs[0].set_ylabel('Accuracy')
    axs[0].legend()
    # Loss plot
    axs[1].plot(history.history['loss'], label='Train Loss')
    axs[1].plot(history.history['val_loss'], label='Validation Loss')
    axs[1].set_title('Model Loss')
    axs[1].set_xlabel('Epoch')
    axs[1].set_ylabel('Loss')
    axs[1].legend()
    plt.show()

plot_training_history(history)