import math
import tensorflow as tf
from typing import Dict, List
from .tfdata import int64_feature, float_feature


class Shard():
    """A shard contains N measurement pertaining to the same key"""
    def __init__(self, path: str, attack_points_info: Dict,
                 measurements_info: Dict, compression: True) -> None:
        self.path = path
        self.attack_points_info = attack_points_info
        self.measurements_info = measurements_info
        self.compression = compression

        # Writer if needed
        self.has_writer = False
        self.writer = None

        # counters
        self.examples = 0
        self.min_values = {}
        self.max_values = {}
        for k in measurements_info.keys():
            self.min_values[k] = math.inf
            self.max_values[k] = 0

        # build and cache tffeature format
        self.features = self._build_tffeature()

    def write(self, attack_points: Dict[str, List[int]],
              measurements: Dict[str, List[float]]):
        """Write example on disk as TFRecord

        Args:
            attack_points: Attack points values.
            measurements: Measurements values.
        """
        with tf.device('/cpu:0'):
            # open writer if needed
            # !do not put in the init to avoid erasing on read
            if not self.has_writer:
                self.writer = tf.io.TFRecordWriter(self.path, self.compression)
                self.has_writer = True
            example = self._to_tfrecord(attack_points, measurements)
            self.writer.write(example)
            self.examples += 1

    def read(self, num=10) -> Dict:
        """Open and read N examples from the shard"""
        _shard = tf.data.TFRecordDataset(self.path,
                                         compression_type=self.compression)
        data = _shard.map(self._from_tfrecord)
        return data.take(num)

    def close(self) -> Dict:
        "close shard and return statistics"
        if not self.writer:
            raise ValueError("Trying to close a shard that was not open")

        self.writer.close()
        return {
            "examples": self.examples,
            "min_values": self.min_values,
            "max_values": self.max_values
        }

    def _to_tfrecord(self, attack_points, measurements):
        """Convert example data into a tfrecord example

        Args:
            attack_points: attack points data
            measurements: measurements data

        Returns:
            TF.train.Example
        """

        # check there are no unexpected values
        for k in attack_points:
            if k not in self.attack_points_info:
                raise ValueError("Attack poiint", k, "not specified")

        for k in measurements:
            if k not in self.measurements_info:
                raise ValueError("Measurement", k, "not specified")

        feature = {}
        # attack points as integers
        for ap_name, info in self.attack_points_info.items():
            expected_len = info['len']
            ap_value = attack_points[ap_name]

            # check that we get the len specified in the info
            if len(ap_value) != expected_len:
                raise ValueError(ap_name, len(ap_value), "don't have the right len", expected_len)

            # convert
            feature[ap_name] = int64_feature(ap_value)

        # measurements as float
        for mname, info in self.measurements_info.items():
            expected_len = info['len']
            measurement = measurements[mname]

            # check that the measurement len match what is specified in info
            if len(measurement) != expected_len:
                raise ValueError(mname, "don't have the right len")

            # min and max
            self.min_values[mname] = min(self.min_values[mname],
                                         float(tf.reduce_min(measurement)))
            self.max_values[mname] = max(self.max_values[mname],
                                         float(tf.reduce_max(measurement)))

            # convert
            feature[mname] = float_feature(measurement)

        tffeats = tf.train.Features(feature=feature)
        record = tf.train.Example(features=tffeats)
        return record.SerializeToString()

    def _from_tfrecord(self, tfrecord):
        """Convert tf_record to dictionary

        Args:
            tf_record: tf_record to parse
        Returns:
            reloaded example as dictionary
        """
        return tf.io.parse_single_example(tfrecord, self._build_tffeature())

    def _build_tffeature(self):
        "build tf feature dictionary based of meta data"
        features = {}

        # attack points
        for k, info in self.attack_points_info.items():
            flen = info['len']
            features[k] = tf.io.FixedLenFeature([flen], tf.int64)

        # measurements
        for k, info in self.measurements_info.items():
            flen = info['len']
            features[k] = tf.io.FixedLenFeature([flen], tf.float32)

        return features