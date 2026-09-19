# ============================================================
# AGRIVISION - PADDY DISEASE DETECTION TRAINING
# EfficientNet-B0
#
# Dataset:
# RiceDiseaseDataset/
# ├── Original/
# └── Augmented/
#
# 8 Classes
# ============================================================

import os
import random
from pathlib import Path

import numpy as np
import tensorflow as tf

from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_class_weight

from tensorflow import keras
from tensorflow.keras import layers
from tensorflow.keras.applications import EfficientNetB0


# ============================================================
# CONFIGURATION
# ============================================================

SEED = 42

random.seed(SEED)
np.random.seed(SEED)
tf.random.set_seed(SEED)

IMG_SIZE = 224
BATCH_SIZE = 32

HEAD_EPOCHS = 10
FINE_TUNE_EPOCHS = 15

LEARNING_RATE = 1e-3
FINE_TUNE_LEARNING_RATE = 1e-5

BASE_DIR = Path(__file__).resolve().parent

DATASET_DIR = BASE_DIR.parent / "RiceDiseaseDataset"

ORIGINAL_DIR = DATASET_DIR / "Original"
AUGMENTED_DIR = DATASET_DIR / "Augmented"

MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH = MODEL_DIR / "paddy_disease_model.keras"


# ============================================================
# CLASS MAPPING
# ============================================================

# Folder name -> final model class name

CLASS_MAPPING = {
    "Bacterial Leaf Blight": "Bacterial Leaf Blight",
    "Brown Spot": "Brown Spot",
    "Healthy Rice Leaf": "Healthy Rice Leaf",
    "Leaf Blast": "Leaf Blast",
    "Leaf scald": "Leaf Scald",
    "Narrow Brown Leaf Spot": "Narrow Brown Leaf Spot",
    "Rice Hispa": "Rice Hispa",
    "Sheath Blight": "Sheath Blight",
}

CLASS_NAMES = list(CLASS_MAPPING.values())

NUM_CLASSES = len(CLASS_NAMES)

CLASS_TO_INDEX = {
    class_name: index
    for index, class_name in enumerate(CLASS_NAMES)
}


# ============================================================
# SUPPORTED IMAGE EXTENSIONS
# ============================================================

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
}


# ============================================================
# FIND IMAGES
# ============================================================

def get_images_from_directory(directory):
    """
    Read all valid images from each class directory.
    """

    image_paths = []
    labels = []

    for folder_name, class_name in CLASS_MAPPING.items():

        class_dir = directory / folder_name

        if not class_dir.exists():
            raise FileNotFoundError(
                f"Class folder not found: {class_dir}"
            )

        class_index = CLASS_TO_INDEX[class_name]

        files = sorted(
            [
                file
                for file in class_dir.iterdir()
                if file.is_file()
                and file.suffix.lower() in IMAGE_EXTENSIONS
            ]
        )

        print(
            f"{directory.name:10s} | "
            f"{class_name:28s} | "
            f"{len(files)} images"
        )

        for file in files:
            image_paths.append(str(file))
            labels.append(class_index)

    return image_paths, labels


# ============================================================
# LOAD ORIGINAL DATA
# ============================================================

print("\n" + "=" * 70)
print("LOADING ORIGINAL DATASET")
print("=" * 70)

original_paths, original_labels = get_images_from_directory(
    ORIGINAL_DIR
)

print(
    f"\nTotal original images: {len(original_paths)}"
)


# ============================================================
# TRAIN / VALIDATION / TEST SPLIT
# ============================================================

print("\n" + "=" * 70)
print("CREATING ORIGINAL TRAIN / VALIDATION / TEST SPLIT")
print("=" * 70)

# First:
# 70% train
# 30% temporary

train_paths, temp_paths, train_labels, temp_labels = (
    train_test_split(
        original_paths,
        original_labels,
        test_size=0.30,
        random_state=SEED,
        stratify=original_labels,
    )
)

# Split remaining 30% into:
# 15% validation
# 15% test

val_paths, test_paths, val_labels, test_labels = (
    train_test_split(
        temp_paths,
        temp_labels,
        test_size=0.50,
        random_state=SEED,
        stratify=temp_labels,
    )
)

print(f"Original training images   : {len(train_paths)}")
print(f"Original validation images : {len(val_paths)}")
print(f"Original testing images    : {len(test_paths)}")


# ============================================================
# LOAD AUGMENTED DATA
# ============================================================

print("\n" + "=" * 70)
print("LOADING AUGMENTED DATA")
print("=" * 70)

augmented_paths, augmented_labels = get_images_from_directory(
    AUGMENTED_DIR
)

print(
    f"\nTotal augmented images: {len(augmented_paths)}"
)


# ============================================================
# ADD AUGMENTED IMAGES ONLY TO TRAINING
# ============================================================

train_paths = train_paths + augmented_paths
train_labels = train_labels + augmented_labels

print("\n" + "=" * 70)
print("FINAL DATASET")
print("=" * 70)

print(f"Training images   : {len(train_paths)}")
print(f"Validation images : {len(val_paths)}")
print(f"Testing images    : {len(test_paths)}")


# ============================================================
# SHUFFLE TRAINING DATA
# ============================================================

train_combined = list(
    zip(train_paths, train_labels)
)

random.Random(SEED).shuffle(train_combined)

train_paths, train_labels = zip(*train_combined)

train_paths = list(train_paths)
train_labels = list(train_labels)


# ============================================================
# IMAGE LOADING FUNCTION
# ============================================================

def load_image(path, label):

    image = tf.io.read_file(path)

    image = tf.image.decode_image(
        image,
        channels=3,
        expand_animations=False,
    )

    image.set_shape(
        [None, None, 3]
    )

    image = tf.image.resize(
        image,
        [IMG_SIZE, IMG_SIZE],
    )

    image = tf.cast(
        image,
        tf.float32,
    )

    return image, label


# ============================================================
# CREATE TF.DATA DATASETS
# ============================================================

def create_dataset(paths, labels, training=False):

    dataset = tf.data.Dataset.from_tensor_slices(
        (
            paths,
            labels,
        )
    )

    if training:
        dataset = dataset.shuffle(
            buffer_size=len(paths),
            seed=SEED,
            reshuffle_each_iteration=True,
        )

    dataset = dataset.map(
        load_image,
        num_parallel_calls=tf.data.AUTOTUNE,
    )

    dataset = dataset.batch(
        BATCH_SIZE
    )

    dataset = dataset.prefetch(
        tf.data.AUTOTUNE
    )

    return dataset


train_dataset = create_dataset(
    train_paths,
    train_labels,
    training=True,
)

validation_dataset = create_dataset(
    val_paths,
    val_labels,
    training=False,
)

test_dataset = create_dataset(
    test_paths,
    test_labels,
    training=False,
)


# ============================================================
# CLASS WEIGHTS
# ============================================================

print("\n" + "=" * 70)
print("CALCULATING CLASS WEIGHTS")
print("=" * 70)

class_weights_array = compute_class_weight(
    class_weight="balanced",
    classes=np.arange(NUM_CLASSES),
    y=np.array(train_labels),
)

class_weights = {
    index: float(weight)
    for index, weight in enumerate(class_weights_array)
}

for index, class_name in enumerate(CLASS_NAMES):

    print(
        f"{class_name:28s} "
        f"weight = {class_weights[index]:.4f}"
    )


# ============================================================
# DATA AUGMENTATION
# ============================================================

data_augmentation = keras.Sequential(
    [
        layers.RandomFlip(
            "horizontal"
        ),

        layers.RandomRotation(
            0.08
        ),

        layers.RandomZoom(
            height_factor=0.10,
            width_factor=0.10,
        ),

        layers.RandomContrast(
            0.10
        ),
    ],
    name="disease_data_augmentation",
)


# ============================================================
# BUILD EFFICIENTNET-B0 MODEL
# ============================================================

print("\n" + "=" * 70)
print("BUILDING EFFICIENTNET-B0")
print("=" * 70)

base_model = EfficientNetB0(
    include_top=False,
    weights="imagenet",
    input_shape=(
        IMG_SIZE,
        IMG_SIZE,
        3,
    ),
)

# Initially freeze pretrained layers

base_model.trainable = False


inputs = keras.Input(
    shape=(
        IMG_SIZE,
        IMG_SIZE,
        3,
    ),
    name="crop_image",
)


x = data_augmentation(inputs)

x = base_model(
    x,
    training=False,
)

x = layers.GlobalAveragePooling2D(
    name="global_average_pooling"
)(x)

x = layers.Dropout(
    0.35,
    name="dropout"
)(x)

outputs = layers.Dense(
    NUM_CLASSES,
    activation="softmax",
    name="disease_prediction",
)(x)


model = keras.Model(
    inputs,
    outputs,
    name="AgriVision_EfficientNetB0",
)


# ============================================================
# COMPILE - STAGE 1
# ============================================================

model.compile(
    optimizer=keras.optimizers.Adam(
        learning_rate=LEARNING_RATE
    ),

    loss=keras.losses.SparseCategoricalCrossentropy(),

    metrics=[
        "accuracy",
    ],
)


print("\nModel created successfully.")

model.summary()


# ============================================================
# CALLBACKS
# ============================================================

callbacks = [

    keras.callbacks.ModelCheckpoint(
        filepath=str(MODEL_PATH),
        monitor="val_accuracy",
        mode="max",
        save_best_only=True,
        verbose=1,
    ),

    keras.callbacks.EarlyStopping(
        monitor="val_accuracy",
        patience=4,
        mode="max",
        restore_best_weights=True,
        verbose=1,
    ),

    keras.callbacks.ReduceLROnPlateau(
        monitor="val_loss",
        factor=0.3,
        patience=2,
        min_lr=1e-7,
        verbose=1,
    ),
]


# ============================================================
# STAGE 1 - TRAIN CLASSIFICATION HEAD
# ============================================================

print("\n" + "=" * 70)
print("STAGE 1 - TRAINING CLASSIFICATION HEAD")
print("=" * 70)

history_head = model.fit(
    train_dataset,

    validation_data=validation_dataset,

    epochs=HEAD_EPOCHS,

    class_weight=class_weights,

    callbacks=callbacks,
)


# ============================================================
# STAGE 2 - FINE TUNING
# ============================================================

print("\n" + "=" * 70)
print("STAGE 2 - FINE TUNING EFFICIENTNET-B0")
print("=" * 70)

# Unfreeze EfficientNet

base_model.trainable = True


# Keep earlier layers frozen.
# Only the later layers are fine-tuned.

fine_tune_from = max(
    0,
    len(base_model.layers) - 40
)

for layer in base_model.layers[
    :fine_tune_from
]:
    layer.trainable = False


# Keep BatchNormalization layers frozen
# for more stable transfer learning.

for layer in base_model.layers:

    if isinstance(
        layer,
        layers.BatchNormalization,
    ):
        layer.trainable = False


print(
    f"Fine-tuning last "
    f"{len(base_model.layers) - fine_tune_from} "
    f"layers."
)


model.compile(
    optimizer=keras.optimizers.Adam(
        learning_rate=FINE_TUNE_LEARNING_RATE
    ),

    loss=keras.losses.SparseCategoricalCrossentropy(),

    metrics=[
        "accuracy",
    ],
)


history_fine = model.fit(
    train_dataset,

    validation_data=validation_dataset,

    epochs=FINE_TUNE_EPOCHS,

    class_weight=class_weights,

    callbacks=callbacks,
)


# ============================================================
# LOAD BEST MODEL
# ============================================================

print("\n" + "=" * 70)
print("LOADING BEST MODEL")
print("=" * 70)

if MODEL_PATH.exists():

    model = keras.models.load_model(
        MODEL_PATH
    )

    print(
        f"Best model loaded from:\n{MODEL_PATH}"
    )

else:

    model.save(
        MODEL_PATH
    )

    print(
        f"Model saved to:\n{MODEL_PATH}"
    )


# ============================================================
# FINAL TEST EVALUATION
# ============================================================

print("\n" + "=" * 70)
print("FINAL TEST EVALUATION")
print("=" * 70)

test_loss, test_accuracy = model.evaluate(
    test_dataset,
    verbose=1,
)

print("\n" + "=" * 70)
print("FINAL MODEL RESULT")
print("=" * 70)

print(
    f"Test Loss     : {test_loss:.4f}"
)

print(
    f"Test Accuracy : {test_accuracy * 100:.2f}%"
)


# ============================================================
# SAVE CLASS NAMES
# ============================================================

CLASS_FILE = MODEL_DIR / "paddy_disease_classes.txt"

with open(
    CLASS_FILE,
    "w",
    encoding="utf-8",
) as file:

    for class_name in CLASS_NAMES:
        file.write(
            class_name + "\n"
        )


# ============================================================
# SAVE FINAL MODEL
# ============================================================

model.save(
    MODEL_PATH
)


print("\n" + "=" * 70)
print("TRAINING COMPLETED")
print("=" * 70)

print(
    f"Model:\n{MODEL_PATH}"
)

print(
    f"\nClasses:\n{CLASS_FILE}"
)

print("\nClasses:")

for index, class_name in enumerate(CLASS_NAMES):

    print(
        f"{index}: {class_name}"
    )

print("\nAgriVision disease model is ready.")