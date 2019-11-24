import logging
import os
from dataclasses import dataclass, field

import numpy as np
import keras

import librosa
import soundfile as sf
from kapre.time_frequency import Spectrogram

"""
The STFT spectrogram of the input signal is fed
into a 2D CNN that predicts the synthesizer parameter
configuration. This configuration is then used to produce
a sound that is similar to the input sound.
"""

"""Audio Samples"""
# NOTE: May need true FM synthesizer generator
# credit: https://beatproduction.net/korg-m1-piano-samples/
m1_sample: str = os.getcwd() + '/audio/samples/M1_Piano_C4.wav'
# credit: https://freewavesamples.com/yamaha-dx7-bass-c2
dx7_sample: str = os.getcwd() + '/audio/samples/Yamaha-DX7-Bass-C2.wav'

"""Audio Pre-processing"""
def input_raw_audio(path: str, sr: int=16384, duration: float=1.) -> tuple:
    # @paper: signal in a duration of 1 second with a sampling rate of 16384Hz
    # @paper: Input (16384 raw audio)
    y_audio, sample_rate = librosa.load(path,
                                        sr=sr, # `None` preserves sample rate
                                        duration=duration,)
    return (y_audio, sample_rate)

def stft_to_audio(S: np.ndarray) -> np.ndarray:
    # Inverse STFT to audio
    # tf.signal.inverse_stft
    return librosa.griffinlim(S)

"""Model Utils"""
def summarize_compile(model: keras.Model):
    model.summary(line_length=80, positions=[.33, .65, .8, 1.])
    # Specify the training configuration (optimizer, loss, metrics)
    model.compile(optimizer=keras.optimizers.Adam(), # Optimizer- Adam [14] optimizer
                  # Loss function to minimize
                  # @paper: Therefore, we converged on using sigmoid activations with binary cross entropy loss.
                  loss=keras.losses.BinaryCrossentropy(),
                  # List of metrics to monitor
                  metrics=[ # @paper: 1) Mean Percentile Rank?
                            keras.metrics.MeanAbsolutePercentageError(),
                            # @paper: 2) Top-k mean accuracy based evaluation
                            # TODO:  metrics.TopKCategoricalAccuracy(),
                            # @paper: 3) Mean Absolute Error based evaluation
                            keras.metrics.MeanAbsoluteError(),])

def fit(model: keras.Model,
        x_train: np.ndarray, y_train: np.ndarray,
        x_val: np.ndarray, y_val: np.ndarray,
        batch_size:int=16, epochs:int=100,) -> keras.Model:

    # @paper:
    # with a minibatch size of 16 for
    # 100 epochs. The best weights for each model were set by
    # employing an early stopping procedure.
    logging.info('# Fit model on training data')
    history = model.fit(x_train, y_train,
                        batch_size=batch_size,
                        epochs=epochs,
                        # @paper:
                        # Early stopping procedure:
                        # We pass some validation for
                        # monitoring validation loss and metrics
                        # at the end of each epoch
                        validation_data=(x_val, y_val),)

    # The returned "history" object holds a record
    # of the loss values and metric values during training
    logging.info('\nhistory dict:', history.history)

    return model

def predict(model: keras.Model,
            x: np.ndarray,
            logam: bool=False,) -> np.ndarray:

    # predict
    result: np.ndarray = model.predict(x=x)

    # shuffle for `channels first`
    is_channels_first: bool = keras.backend.image_data_format == 'channels_first'
    result = result[0, 0] if is_channels_first else result[0, :, :, 0]

    return result

"""Model Architecture"""
# @ paper:
# 1 2D Strided Convolution Layer C(38,13,26,13,26)
# where C(F,K1,K2,S1,S2) stands for a ReLU activated
# 2D strided convolutional layer with F filters in size of (K1,K2)
# and strides (S1,S2).

@dataclass
class ArchLayer:
    filters: int
    window_size: tuple
    strides: tuple
    activation: str = 'relu'

def assemble_model(src: np.ndarray, arch_layers: list) -> keras.Model:
    inputs = keras.Input(shape=src.shape, name='stft')

    # TODO parametrize, explain
    n_dft: int = 128
    n_hop: int = 64

    # @paper: Spectrogram based CNN that receives the (log) spectrogram matrix as input

    # abs(Spectrogram) in a shape of 2D data, i.e.,
    # `(None, n_channel, n_freq, n_time)` if `'channels_first'`,
    # `(None, n_freq, n_time, n_channel)` if `'channels_last'`,
    x = Spectrogram(n_dft=n_dft, n_hop=n_hop, input_shape=src.shape,
                    trainable_kernel=True, name='static_stft',
                    image_data_format='channels_first',)(inputs)

    for arch_layer in arch_layers:
        x = keras.layers.Conv2D(arch_layer.filters,
                                arch_layer.window_size,
                                strides=arch_layer.strides,
                                activation=arch_layer.activation,
                                data_format='channels_first',)(x) # data_format=None, dilation_rate=(1, 1), activation=None, use_bias=True, kernel_initializer='glorot_uniform', bias_initializer='zeros', kernel_regularizer=None, bias_regularizer=None, activity_regularizer=None, kernel_constraint=None, bias_constraint=None)

    # @paper: sigmoid activations with binary cross entropy loss

    # @paper: FC-512
    x = keras.layers.Dense(512)(x)

    # @paper: FC-368(sigmoid)
    outputs = keras.layers.Dense(368, activation='sigmoid', name='predictions')(x)

    return keras.Model(inputs=inputs, outputs=outputs)


if __name__ == "__main__":
    # load audio sample

    # define input path
    input_audio_path: str = os.getenv('AUDIO_WAV_INPUT', dx7_sample)
    # define audio sample max duration
    duration: float = 1
    # extract raw audio
    y_audio, sample_rate = input_raw_audio(input_audio_path, duration=duration)

    # model assembly
    """Conv 1 (2 Layers)"""
    c1: ArchLayer = ArchLayer(38, (13, 26), (13,26))
    c1_layers: list = [c1]

    """Conv 6XL, 7 Layers"""
    # TODO

    # @kapre: input should be a 2D array, `(audio_channel, audio_length)`.
    input_2d: np.ndarray = np.expand_dims(y_audio, axis=0)

    model: keras.Model = assemble_model(input_2d,
                                        arch_layers=c1_layers,)

    # TODO parametrize
    n_samples: int = 1000
    x_train: np.ndarray = np.array([input_2d] * n_samples)
    y_train: np.ndarray = np.random.uniform(size=(n_samples,) + model.output_shape[1:])

    # Reserve samples for validation
    slice = int(n_samples * .2)
    x_val = x_train[-slice:]
    y_val = y_train[-slice:]
    x_train = x_train[:-slice]
    y_train = y_train[:-slice]

    # summarize and compile the model
    summarize_compile(model)

    # fit and predict
    model: keras.Model = fit(model,
                             x_train, y_train,
                             x_val, y_val,
                             epochs=1)

    # TEMP
    if os.getenv('EXPERIMENTATION', True):
        # freeze model
        model.save('models/saved/dx7_sample.h5')

        # predict
        x_test: np.ndarray = np.array([input_2d] * 1)
        result: np.ndarray = predict(model, x_test, sample_rate)

        # write audio
        new_audio: np.ndarray = stft_to_audio(result)
        sf.write('audio/outputs/new_audio.wav', new_audio, sample_rate)
