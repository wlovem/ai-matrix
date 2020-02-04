
import os
import tensorflow as tf
from tensorflow.python.framework import tensor_shape
from tensorflow.python.framework import dtypes
from tensorflow.python.ops.rnn_cell import GRUCell
from tensorflow.python.ops.rnn_cell import LSTMCell
from tensorflow.python.ops.rnn import bidirectional_dynamic_rnn as bi_rnn
# from tensorflow.python.ops.rnn import dynamic_rnn
from rnn import dynamic_rnn
from utils import *
from Dice import dice

from tensorflow.python import ipu
from tensorflow.python.ipu.ops.embedding_ops import embedding_lookup as ipu_embedding_lookup

cpu_embedding_lookup = True
import pdb

class Model(object):
    def __init__(self, run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE, data_type='FP32', use_negsampling = False):
        if data_type == 'FP32':
            self.model_dtype = tf.float32
        elif data_type == 'FP16':
            self.model_dtype = tf.float16
        else:
            raise ValueError("Invalid model data type: %s" % data_type)

        self.options = run_options
        self.EMBEDDING_DIM = EMBEDDING_DIM
        self.HIDDEN_SIZE = HIDDEN_SIZE
        self.ATTENTION_SIZE = ATTENTION_SIZE
        self.aux_loss = 0
        self.lr = tf.placeholder(tf.float32)
        self.n_uid = n_uid
        self.n_mid = n_mid
        self.n_cat = n_cat
        self.use_negsampling = use_negsampling

        self.base_path = os.getcwd()
        self.lib_path = os.path.join(self.base_path, "cpu_op.so")

    def build_input_gpu(self):
        with tf.name_scope('Inputs'):
            self.mid_his_batch_ph = tf.placeholder(tf.int32, [None, None], name='mid_his_batch_ph')
            self.cat_his_batch_ph = tf.placeholder(tf.int32, [None, None], name='cat_his_batch_ph')
            self.uid_batch_ph = tf.placeholder(tf.int32, [None, ], name='uid_batch_ph')
            self.mid_batch_ph = tf.placeholder(tf.int32, [None, ], name='mid_batch_ph')
            self.cat_batch_ph = tf.placeholder(tf.int32, [None, ], name='cat_batch_ph')
            self.mask = tf.placeholder(self.model_dtype, [None, None], name='mask')
            self.seq_len_ph = tf.placeholder(tf.int32, [None], name='seq_len_ph')
            self.target_ph = tf.placeholder(self.model_dtype, [None, None], name='target_ph')
            self.lr = tf.placeholder(tf.float64, [])
            self.use_negsampling = use_negsampling
            if use_negsampling:
                self.noclk_mid_batch_ph = tf.placeholder(tf.int32, [None, None, None], name='noclk_mid_batch_ph')  # generate 3 item IDs from negative sampling.
                self.noclk_cat_batch_ph = tf.placeholder(tf.int32, [None, None, None], name='noclk_cat_batch_ph')

    def build_input_ipu(self):
        with tf.name_scope('Inputs'):
            self.mid_his_batch_ph = tf.placeholder(tf.int32, [self.options.batch_size, self.options.sequence_length], name='mid_his_batch_ph')
            self.cat_his_batch_ph = tf.placeholder(tf.int32, [self.options.batch_size, self.options.sequence_length], name='cat_his_batch_ph')
            self.uid_batch_ph = tf.placeholder(tf.int32, [self.options.batch_size], name='uid_batch_ph')
            self.mid_batch_ph = tf.placeholder(tf.int32, [self.options.batch_size], name='mid_batch_ph')
            self.cat_batch_ph = tf.placeholder(tf.int32, [self.options.batch_size], name='cat_batch_ph')
            self.mask = tf.placeholder(self.model_dtype, [self.options.batch_size, self.options.sequence_length], name='mask')
            self.seq_len_ph = tf.placeholder(tf.int32, [self.options.batch_size], name='seq_len_ph')
            self.target_ph = tf.placeholder(self.model_dtype, [self.options.batch_size, 2], name='target_ph')
            if self.use_negsampling:
                self.noclk_mid_batch_ph = tf.placeholder(tf.int32, [self.options.batch_size, self.options.sequence_length, self.options.negative_samples], name='noclk_mid_batch_ph')  # generate 3 item IDs from negative sampling.
                self.noclk_cat_batch_ph = tf.placeholder(tf.int32, [self.options.batch_size, self.options.sequence_length, self.options.negative_samples], name='noclk_cat_batch_ph')

    def build_embedding_input_ipu(self):
        if cpu_embedding_lookup:
            self.uid_embeddings_var = tf.get_variable("uid_embedding_var",
                                                    shape=[self.n_uid, self.EMBEDDING_DIM],
                                                    initializer=tf.random_uniform_initializer(minval=-0.05, maxval=0.05, dtype=self.model_dtype),
                                                    dtype=self.model_dtype)
            
            self.mid_embeddings_var = tf.get_variable("mid_embedding_var",
                                                        shape=[self.n_mid, self.EMBEDDING_DIM],
                                                        initializer=tf.random_uniform_initializer(minval=-0.05, maxval=0.05, dtype=self.model_dtype),
                                                        dtype=self.model_dtype)
            
            self.cat_embeddings_var = tf.get_variable("cat_embedding_var",
                                                        shape=[self.n_cat, self.EMBEDDING_DIM],
                                                        initializer=tf.random_uniform_initializer(minval=-0.05, maxval=0.05, dtype=self.model_dtype),
                                                        dtype=self.model_dtype)

    def build_embedding_gpu(self):
        # Embedding layer
        with tf.name_scope('Embedding_layer'):
            self.uid_embeddings_var = tf.get_variable("uid_embedding_var", [n_uid, EMBEDDING_DIM], dtype=self.model_dtype)
            tf.summary.histogram('uid_embeddings_var', self.uid_embeddings_var)
            self.uid_batch_embedded = tf.nn.embedding_lookup(self.uid_embeddings_var, self.uid_batch_ph)

            self.mid_embeddings_var = tf.get_variable("mid_embedding_var", [n_mid, EMBEDDING_DIM], dtype=self.model_dtype)
            tf.summary.histogram('mid_embeddings_var', self.mid_embeddings_var)
            self.mid_batch_embedded = tf.nn.embedding_lookup(self.mid_embeddings_var, self.mid_batch_ph)
            self.mid_his_batch_embedded = tf.nn.embedding_lookup(self.mid_embeddings_var, self.mid_his_batch_ph)
            if self.use_negsampling:
                self.noclk_mid_his_batch_embedded = tf.nn.embedding_lookup(self.mid_embeddings_var, self.noclk_mid_batch_ph)

            self.cat_embeddings_var = tf.get_variable("cat_embedding_var", [n_cat, EMBEDDING_DIM], dtype=self.model_dtype)
            tf.summary.histogram('cat_embeddings_var', self.cat_embeddings_var)
            self.cat_batch_embedded = tf.nn.embedding_lookup(self.cat_embeddings_var, self.cat_batch_ph)
            self.cat_his_batch_embedded = tf.nn.embedding_lookup(self.cat_embeddings_var, self.cat_his_batch_ph)
            if self.use_negsampling:
                self.noclk_cat_his_batch_embedded = tf.nn.embedding_lookup(self.cat_embeddings_var, self.noclk_cat_batch_ph)

    def build_embedding_ipu(self):
        print("build_embedding_ipu")
        # Embedding layer
        with tf.variable_scope('Embedding_layer', use_resource=True, reuse=tf.AUTO_REUSE):
            embedding_lookup_shape = [self.options.batch_size, self.EMBEDDING_DIM]
            
            print("embedding_lookup_shape:" + str(embedding_lookup_shape))
            if cpu_embedding_lookup:
                outputs = {
                   "output_types": [dtypes.float32],
                   "output_shapes": [tensor_shape.TensorShape(embedding_lookup_shape)],
                }
                self.uid_batch_embedded = ipu.custom_ops.cpu_user_operation([self.uid_embeddings_var, self.uid_batch_ph],
                                              self.lib_path,
                                              name='cpu_uid_embedding_lookup',
                                              op_name='cpuCallback',
                                              outs=outputs)
                self.mid_batch_embedded = ipu.custom_ops.cpu_user_operation([self.mid_embeddings_var, self.mid_batch_ph],
                                              self.lib_path,
                                              name='cpu_mid_embedding_lookup',
                                              op_name='cpuCallback',
                                              outs=outputs)
                self.mid_his_batch_embedded = ipu.custom_ops.cpu_user_operation([self.mid_embeddings_var, self.mid_his_batch_ph],
                                              self.lib_path,
                                              name='cpu_mid_his_embedding_lookup',
                                              op_name='cpuCallback',
                                              outs=outputs)
                print("self.uid_batch_embedded:" + str(self.uid_batch_embedded))
                print("self.mid_batch_embedded:" + str(self.mid_batch_embedded))
                print("self.mid_his_batch_embedded:" + str(self.mid_his_batch_embedded))
                if self.use_negsampling:
                    self.noclk_mid_his_batch_embedded = ipu.custom_ops.cpu_user_operation([self.mid_embeddings_var, self.noclk_mid_batch_ph],
                                                self.lib_path,
                                                name='cpu_noclk_mid_his_batch_embedded',
                                                op_name='cpuCallback',
                                                outs=outputs)
                    self.noclk_cat_his_batch_embedded = ipu.custom_ops.cpu_user_operation([self.cat_embeddings_var, self.noclk_cat_batch_ph],
                                              self.lib_path,
                                              name='cpu_noclk_cat_his_batch_embedded',
                                              op_name='cpuCallback',
                                              outs=outputs)

                    print("self.noclk_mid_his_batch_embedded:" + str(type(self.noclk_mid_his_batch_embedded)))
                    print("self.noclk_cat_his_batch_embedded:" + str(self.noclk_cat_his_batch_embedded))
                
                self.cat_batch_embedded = ipu.custom_ops.cpu_user_operation([self.cat_embeddings_var, self.cat_batch_ph],
                                              self.lib_path,
                                              name='cpu_cat_embedding_lookup',
                                              op_name='cpuCallback',
                                              outs=outputs)
                self.cat_his_batch_embedded = ipu.custom_ops.cpu_user_operation([self.cat_embeddings_var, self.cat_his_batch_ph],
                                              self.lib_path,
                                              name='cpu_cat_his_embedding_lookup',
                                              op_name='cpuCallback',
                                              outs=outputs)
            else:
                self.uid_embeddings_var = tf.get_variable("uid_embedding_var",
                                                            shape=[self.n_uid, self.EMBEDDING_DIM],
                                                            initializer=tf.random_uniform_initializer(minval=-0.05, maxval=0.05, dtype=self.model_dtype),
                                                            dtype=self.model_dtype)
                self.mid_embeddings_var = tf.get_variable("mid_embedding_var",
                                                            shape=[self.n_mid, self.EMBEDDING_DIM],
                                                            initializer=tf.random_uniform_initializer(minval=-0.05, maxval=0.05, dtype=self.model_dtype),
                                                            dtype=self.model_dtype)
                self.cat_embeddings_var = tf.get_variable("cat_embedding_var",
                                                        shape=[self.n_cat, self.EMBEDDING_DIM],
                                                        initializer=tf.random_uniform_initializer(minval=-0.05, maxval=0.05, dtype=self.model_dtype),
                                                        dtype=self.model_dtype)

                self.uid_batch_embedded = ipu_embedding_lookup(self.uid_embeddings_var, self.uid_batch_ph,  name='uid_embedding_lookup')
                self.mid_batch_embedded = ipu_embedding_lookup(self.mid_embeddings_var, self.mid_batch_ph,  name='mid_embedding_lookup')
                self.mid_his_batch_embedded = ipu_embedding_lookup(self.mid_embeddings_var, self.mid_his_batch_ph,  name='mid_his_embedding_lookup')
            
                if self.use_negsampling:
                    self.noclk_mid_his_batch_embedded = ipu_embedding_lookup(self.mid_embeddings_var, self.noclk_mid_batch_ph, name='noclk_mid_his_batch_embedded')
                    self.noclk_cat_his_batch_embedded = ipu_embedding_lookup(self.cat_embeddings_var, self.noclk_cat_batch_ph, name='noclk_cat_his_batch_embedded')

                self.cat_batch_embedded = ipu_embedding_lookup(self.cat_embeddings_var, self.cat_batch_ph,  name='cat_embedding_lookup')
                self.cat_his_batch_embedded = ipu_embedding_lookup(self.cat_embeddings_var, self.cat_his_batch_ph,  name='cat_his_embedding_lookup')

        self.item_eb = tf.concat([self.mid_batch_embedded, self.cat_batch_embedded], 1)
        self.item_his_eb = tf.concat([self.mid_his_batch_embedded, self.cat_his_batch_embedded], 2)
        self.item_his_eb_sum = tf.reduce_sum(self.item_his_eb, 1)

        print("use negative sampling:" + str(self.use_negsampling))
        if self.use_negsampling:
            print("use negative sampling")
            print(tf.shape(self.noclk_mid_his_batch_embedded))
            print(tf.shape(self.noclk_cat_his_batch_embedded))
            a = self.noclk_mid_his_batch_embedded[:, :, 0, :]
            b = self.noclk_cat_his_batch_embedded[:, :, 0, :]
            self.noclk_item_his_eb = tf.concat(
                [a, b], -1)  # 0 means only using the first negative item ID. 3 item IDs are inputed in the line 24.
            self.noclk_item_his_eb = tf.reshape(self.noclk_item_his_eb,
                                                [-1, tf.shape(self.noclk_mid_his_batch_embedded)[1], 36])  # cat embedding 18 concate item embedding 18.

            self.noclk_his_eb = tf.concat([self.noclk_mid_his_batch_embedded, self.noclk_cat_his_batch_embedded], -1)
            self.noclk_his_eb_sum_1 = tf.reduce_sum(self.noclk_his_eb, 2)
            self.noclk_his_eb_sum = tf.reduce_sum(self.noclk_his_eb_sum_1, 1)

    def build_fcn_net(self, inp, use_dice = False):
        def dtype_getter(getter, name, dtype=None, *args, **kwargs):
            var = getter(name, dtype=self.model_dtype, *args, **kwargs)
            return var

        with tf.variable_scope("fcn", custom_getter=dtype_getter, dtype=self.model_dtype):
            bn1 = tf.layers.batch_normalization(inputs=inp, name='bn1')
            dnn1 = tf.layers.dense(bn1, 200, activation=None, name='f1')
            if use_dice:
                dnn1 = dice(dnn1, name='dice_1', data_type=self.model_dtype)
            else:
                dnn1 = prelu(dnn1, 'prelu1')

            dnn2 = tf.layers.dense(dnn1, 80, activation=None, name='f2')
            if use_dice:
                dnn2 = dice(dnn2, name='dice_2', data_type=self.model_dtype)
            else:
                dnn2 = prelu(dnn2, 'prelu2')
            dnn3 = tf.layers.dense(dnn2, 2, activation=None, name='f3')
            self.y_hat = tf.nn.softmax(dnn3) + 0.00000001

            with tf.name_scope("Metrics"):
                # with tf.variable_scope("Metrics", custom_getter=dtype_getter, dtype=self.model_dtype):
                # Cross-entropy loss and optimizer initialization
                ctr_loss = - tf.reduce_mean(tf.log(self.y_hat) * self.target_ph)
                self.loss = ctr_loss
                if self.use_negsampling:
                    self.loss += self.aux_loss
                tf.summary.scalar('loss', self.loss)
                self.optimizer = tf.train.GradientDescentOptimizer(learning_rate=self.lr).minimize(self.loss)

                # Accuracy metric
                self.accuracy = tf.reduce_mean(tf.cast(tf.equal(tf.round(self.y_hat), self.target_ph), self.model_dtype))
                tf.summary.scalar('accuracy', self.accuracy)

            self.merged = tf.summary.merge_all()

    def auxiliary_loss(self, h_states, click_seq, noclick_seq, mask, stag = None):
        def dtype_getter(getter, name, dtype=None, *args, **kwargs):
            var = getter(name, dtype=self.model_dtype, *args, **kwargs)
            return var

        with tf.variable_scope("aux_loss", custom_getter=dtype_getter, dtype=self.model_dtype):
            mask = tf.cast(mask, self.model_dtype)
            click_input_ = tf.concat([h_states, click_seq], -1)
            noclick_input_ = tf.concat([h_states, noclick_seq], -1)
            click_prop_ = self.auxiliary_net(click_input_, stag = stag)[:, :, 0]
            noclick_prop_ = self.auxiliary_net(noclick_input_, stag = stag)[:, :, 0]
            click_loss_ = - tf.reshape(tf.log(click_prop_), [-1, tf.shape(click_seq)[1]]) * mask
            noclick_loss_ = - tf.reshape(tf.log(1.0 - noclick_prop_), [-1, tf.shape(noclick_seq)[1]]) * mask
            loss_ = tf.reduce_mean(click_loss_ + noclick_loss_)
            return loss_

    def auxiliary_net(self, in_, stag='auxiliary_net'):
        def dtype_getter(getter, name, dtype=None, *args, **kwargs):
            var = getter(name, dtype=self.model_dtype, *args, **kwargs)
            return var

        with tf.variable_scope("aux_net", custom_getter=dtype_getter, dtype=self.model_dtype):
            bn1 = tf.layers.batch_normalization(inputs=in_, name='bn1' + stag, reuse=tf.AUTO_REUSE)
            dnn1 = tf.layers.dense(bn1, 100, activation=None, name='f1' + stag, reuse=tf.AUTO_REUSE)
            dnn1 = tf.nn.sigmoid(dnn1)
            dnn2 = tf.layers.dense(dnn1, 50, activation=None, name='f2' + stag, reuse=tf.AUTO_REUSE)
            dnn2 = tf.nn.sigmoid(dnn2)
            dnn3 = tf.layers.dense(dnn2, 2, activation=None, name='f3' + stag, reuse=tf.AUTO_REUSE)
            y_hat = tf.nn.softmax(dnn3) + 0.00000001
            return y_hat

    def build_train_gpu(self):
        self.build_embedding_gpu()
        self.build_graph()
        return self.loss, self.accuracy, 0

    def build_train_ipu(self):
        self.build_embedding_ipu()
        self.build_graph()
        return self.loss, self.accuracy, 0

    def train(self, sess, inps, ipu_output=None):
        if not ipu_output:
            if self.use_negsampling:
                loss, accuracy, aux_loss, _ = sess.run([self.loss, self.accuracy, self.aux_loss, self.optimizer], feed_dict={
                    self.uid_batch_ph: inps[0],
                    self.mid_batch_ph: inps[1],
                    self.cat_batch_ph: inps[2],
                    self.mid_his_batch_ph: inps[3],
                    self.cat_his_batch_ph: inps[4],
                    self.mask: inps[5],
                    self.target_ph: inps[6],
                    self.seq_len_ph: inps[7],
                    self.lr: inps[8],
                    self.noclk_mid_batch_ph: inps[9],
                    self.noclk_cat_batch_ph: inps[10],
                })
                return loss, accuracy, aux_loss
            loss, accuracy, _ = sess.run([self.loss, self.accuracy, self.optimizer], feed_dict={
                self.uid_batch_ph: inps[0],
                self.mid_batch_ph: inps[1],
                self.cat_batch_ph: inps[2],
                self.mid_his_batch_ph: inps[3],
                self.cat_his_batch_ph: inps[4],
                self.mask: inps[5],
                self.target_ph: inps[6],
                self.seq_len_ph: inps[7],
                self.lr: inps[8],
            })
            return loss, accuracy, 0

        if self.use_negsampling:
            loss, accuracy, aux_loss = sess.run(ipu_output, feed_dict={
                self.uid_batch_ph: inps[0],
                self.mid_batch_ph: inps[1],
                self.cat_batch_ph: inps[2],
                self.mid_his_batch_ph: inps[3],
                self.cat_his_batch_ph: inps[4],
                self.mask: inps[5],
                self.target_ph: inps[6],
                self.seq_len_ph: inps[7],
                self.lr: inps[8],
                self.noclk_mid_batch_ph: inps[9],
                self.noclk_cat_batch_ph: inps[10],
            })
            return loss, accuracy, aux_loss
        loss, accuracy, _ = sess.run(ipu_output, feed_dict={
            self.uid_batch_ph: inps[0],
            self.mid_batch_ph: inps[1],
            self.cat_batch_ph: inps[2],
            self.mid_his_batch_ph: inps[3],
            self.cat_his_batch_ph: inps[4],
            self.mask: inps[5],
            self.target_ph: inps[6],
            self.seq_len_ph: inps[7],
            self.lr: inps[8],
        })
        return loss, accuracy, 0


    def calculate(self, sess, inps):
        if self.use_negsampling:
            probs, loss, accuracy, aux_loss = sess.run([self.y_hat, self.loss, self.accuracy, self.aux_loss], feed_dict={
                self.uid_batch_ph: inps[0],
                self.mid_batch_ph: inps[1],
                self.cat_batch_ph: inps[2],
                self.mid_his_batch_ph: inps[3],
                self.cat_his_batch_ph: inps[4],
                self.mask: inps[5],
                self.target_ph: inps[6],
                self.seq_len_ph: inps[7],
                self.noclk_mid_batch_ph: inps[8],
                self.noclk_cat_batch_ph: inps[9],
            })
            return probs, loss, accuracy, aux_loss
        else:
            probs, loss, accuracy = sess.run([self.y_hat, self.loss, self.accuracy], feed_dict={
                self.uid_batch_ph: inps[0],
                self.mid_batch_ph: inps[1],
                self.cat_batch_ph: inps[2],
                self.mid_his_batch_ph: inps[3],
                self.cat_his_batch_ph: inps[4],
                self.mask: inps[5],
                self.target_ph: inps[6],
                self.seq_len_ph: inps[7]
            })
            return probs, loss, accuracy, 0

    def save(self, sess, path):
        saver = tf.train.Saver()
        saver.save(sess, save_path=path)

    def restore(self, sess, path):
        saver = tf.train.Saver()
        saver.restore(sess, save_path=path)
        print('model restored from %s' % path)


class Model_DIN_V2_Gru_att_Gru(Model):
    def __init__(self, run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE, use_negsampling=False):
        super(Model_DIN_V2_Gru_att_Gru, self).__init__(run_options, n_uid, n_mid, n_cat,
                                                       EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE,
                                                       use_negsampling)

    def build_graph(self):
        # RNN layer(-s)
        with tf.name_scope('rnn_1'):
            rnn_outputs, _ = dynamic_rnn(GRUCell(self.HIDDEN_SIZE), inputs=self.item_his_eb, max_iteration = self.options.max_rnn_while_loops,
                                         sequence_length=self.seq_len_ph, dtype=tf.float32,
                                         scope="gru1")
            tf.summary.histogram('GRU_outputs', rnn_outputs)

        # Attention layer
        with tf.name_scope('Attention_layer_1'):
            att_outputs, alphas = din_fcn_attention(self.item_eb, rnn_outputs, self.ATTENTION_SIZE, self.mask,
                                                    softmax_stag=1, stag='1_1', mode='LIST', return_alphas=True)
            tf.summary.histogram('alpha_outputs', alphas)

        with tf.name_scope('rnn_2'):
            rnn_outputs2, final_state2 = dynamic_rnn(GRUCell(self.HIDDEN_SIZE), inputs=att_outputs, max_iteration = self.options.max_rnn_while_loops,
                                                     sequence_length=self.seq_len_ph, dtype=tf.float32,
                                                     scope="gru2")
            tf.summary.histogram('GRU2_Final_State', final_state2)

        inp = tf.concat([self.uid_batch_embedded, self.item_eb, self.item_his_eb_sum, self.item_eb * self.item_his_eb_sum, final_state2], 1)
        # Fully connected layer
        self.build_fcn_net(inp, use_dice=True)


class Model_DIN_V2_Gru_Gru_att(Model):
    def __init__(self, run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE, use_negsampling=False):
        super(Model_DIN_V2_Gru_Gru_att, self).__init__(run_options, n_uid, n_mid, n_cat,
                                                       EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE,
                                                       use_negsampling)

        # RNN layer(-s)
        with tf.name_scope('rnn_1'):
            rnn_outputs, _ = dynamic_rnn(GRUCell(HIDDEN_SIZE), inputs=self.item_his_eb, max_iteration = self.options.max_rnn_while_loops,
                                         sequence_length=self.seq_len_ph, dtype=tf.float32,
                                         scope="gru1")
            tf.summary.histogram('GRU_outputs', rnn_outputs)

        with tf.name_scope('rnn_2'):
            rnn_outputs2, _ = dynamic_rnn(GRUCell(HIDDEN_SIZE), inputs=rnn_outputs, max_iteration = self.options.max_rnn_while_loops,
                                          sequence_length=self.seq_len_ph, dtype=tf.float32,
                                          scope="gru2")
            tf.summary.histogram('GRU2_outputs', rnn_outputs2)

        # Attention layer
        with tf.name_scope('Attention_layer_1'):
            att_outputs, alphas = din_fcn_attention(self.item_eb, rnn_outputs2, ATTENTION_SIZE, self.mask,
                                                    softmax_stag=1, stag='1_1', mode='LIST', return_alphas=True)
            att_fea = tf.reduce_sum(att_outputs, 1)
            tf.summary.histogram('att_fea', att_fea)

        inp = tf.concat([self.uid_batch_embedded, self.item_eb, self.item_his_eb_sum, self.item_eb * self.item_his_eb_sum, att_fea], 1)
        self.build_fcn_net(inp, use_dice=True)


class Model_WideDeep(Model):
    def __init__(self, run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE, use_negsampling=False):
        super(Model_WideDeep, self).__init__(run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE,
                                             ATTENTION_SIZE,
                                             use_negsampling)

        inp = tf.concat([self.uid_batch_embedded, self.item_eb, self.item_his_eb_sum], 1)
        # Fully connected layer
        bn1 = tf.layers.batch_normalization(inputs=inp, name='bn1')
        dnn1 = tf.layers.dense(bn1, 200, activation=None, name='f1')
        dnn1 = prelu(dnn1, 'p1')
        dnn2 = tf.layers.dense(dnn1, 80, activation=None, name='f2')
        dnn2 = prelu(dnn2, 'p2')
        dnn3 = tf.layers.dense(dnn2, 2, activation=None, name='f3')
        d_layer_wide = tf.concat([tf.concat([self.item_eb, self.item_his_eb_sum], axis=-1), self.item_eb * self.item_his_eb_sum], axis=-1)
        d_layer_wide = tf.layers.dense(d_layer_wide, 2, activation=None, name='f_fm')
        self.y_hat = tf.nn.softmax(dnn3 + d_layer_wide)

        with tf.name_scope('Metrics'):
            # Cross-entropy loss and optimizer initialization
            self.loss = - tf.reduce_mean(tf.log(self.y_hat) * self.target_ph)
            tf.summary.scalar('loss', self.loss)
            self.optimizer = tf.train.GradientDescentOptimizer(learning_rate=self.lr).minimize(self.loss)

            # Accuracy metric
            self.accuracy = tf.reduce_mean(tf.cast(tf.equal(tf.round(self.y_hat), self.target_ph), tf.float32))
            tf.summary.scalar('accuracy', self.accuracy)
        self.merged = tf.summary.merge_all()


class Model_DIN_V2_Gru_QA_attGru(Model):
    def __init__(self, run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE, use_negsampling=False):
        super(Model_DIN_V2_Gru_QA_attGru, self).__init__(run_options, n_uid, n_mid, n_cat,
                                                         EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE,
                                                         use_negsampling)

        # RNN layer(-s)
        with tf.name_scope('rnn_1'):
            rnn_outputs, _ = dynamic_rnn(GRUCell(HIDDEN_SIZE), inputs=self.item_his_eb, max_iteration = self.options.max_rnn_while_loops,
                                         sequence_length=self.seq_len_ph, dtype=tf.float32,
                                         scope="gru1")
            tf.summary.histogram('GRU_outputs', rnn_outputs)

        # Attention layer
        with tf.name_scope('Attention_layer_1'):
            att_outputs, alphas = din_fcn_attention(self.item_eb, rnn_outputs, ATTENTION_SIZE, self.mask,
                                                    softmax_stag=1, stag='1_1', mode='LIST', return_alphas=True)
            tf.summary.histogram('alpha_outputs', alphas)

        with tf.name_scope('rnn_2'):
            rnn_outputs2, final_state2 = dynamic_rnn(QAAttGRUCell(HIDDEN_SIZE), inputs=rnn_outputs, max_iteration = self.options.max_rnn_while_loops,
                                                     att_scores = tf.expand_dims(alphas, -1),
                                                     sequence_length=self.seq_len_ph, dtype=tf.float32,
                                                     scope="gru2")
            tf.summary.histogram('GRU2_Final_State', final_state2)

        inp = tf.concat([self.uid_batch_embedded, self.item_eb, self.item_his_eb_sum, self.item_eb * self.item_his_eb_sum, final_state2], 1)
        self.build_fcn_net(inp, use_dice=True)


class Model_DNN(Model):
    def __init__(self, run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE, use_negsampling=False):
        super(Model_DNN, self).__init__(run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE,
                                        ATTENTION_SIZE,
                                        use_negsampling)

        inp = tf.concat([self.uid_batch_embedded, self.item_eb, self.item_his_eb_sum], 1)
        self.build_fcn_net(inp, use_dice=False)


class Model_PNN(Model):
    def __init__(self, run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE, use_negsampling=False):
        super(Model_PNN, self).__init__(run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE,
                                        ATTENTION_SIZE,
                                        use_negsampling)

        inp = tf.concat([self.uid_batch_embedded, self.item_eb, self.item_his_eb_sum,
                         self.item_eb * self.item_his_eb_sum], 1)

        # Fully connected layer
        self.build_fcn_net(inp, use_dice=False)


class Model_DIN(Model):
    def __init__(self, run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE, use_negsampling=False):
        super(Model_DIN, self).__init__(run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE,
                                        ATTENTION_SIZE,
                                        use_negsampling)

    def build_graph(self):
        # Attention layer
        with tf.name_scope('Attention_layer'):
            attention_output = din_attention(self.item_eb, self.item_his_eb, self.ATTENTION_SIZE, self.mask)
            att_fea = tf.reduce_sum(attention_output, 1)
            tf.summary.histogram('att_fea', att_fea)
        inp = tf.concat([self.uid_batch_embedded, self.item_eb, self.item_his_eb_sum, self.item_eb * self.item_his_eb_sum, att_fea], -1)
        # Fully connected layer
        self.build_fcn_net(inp, use_dice=True)


class Model_DIN_V2_Gru_Vec_attGru_Neg(Model):
    def __init__(self, run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE, data_type='FP32', use_negsampling=True):
        super(Model_DIN_V2_Gru_Vec_attGru_Neg, self).__init__(run_options, n_uid, n_mid, n_cat,
                                                              EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE, data_type,
                                                              use_negsampling)

    def build_graph(self):
        def dtype_getter(getter, name, dtype=None, *args, **kwargs):
            var = getter(name, dtype=self.model_dtype, *args, **kwargs)
            return var

        with tf.variable_scope("dien", custom_getter=dtype_getter, dtype=self.model_dtype):
            # RNN layer(-s)
            with tf.name_scope('rnn_1'):
                rnn_outputs, _ = dynamic_rnn(GRUCell(self.HIDDEN_SIZE), inputs=self.item_his_eb, max_iteration = self.options.max_rnn_while_loops,
                                             sequence_length=self.seq_len_ph, dtype=self.model_dtype,
                                             scope="gru1")
                tf.summary.histogram('GRU_outputs', rnn_outputs)

            aux_loss_1 = self.auxiliary_loss(rnn_outputs[:, :-1, :], self.item_his_eb[:, 1:, :],
                                             self.noclk_item_his_eb[:, 1:, :],
                                             self.mask[:, 1:], stag="gru")
            self.aux_loss = aux_loss_1

            # Attention layer
            with tf.name_scope('Attention_layer_1'):
                att_outputs, alphas = din_fcn_attention(self.item_eb, rnn_outputs, self.ATTENTION_SIZE, self.mask,
                                                        softmax_stag=1, stag='1_1', mode='LIST', return_alphas=True)
                tf.summary.histogram('alpha_outputs', alphas)

            with tf.name_scope('rnn_2'):
                rnn_outputs2, final_state2 = dynamic_rnn(VecAttGRUCell(self.HIDDEN_SIZE), inputs=rnn_outputs, max_iteration = self.options.max_rnn_while_loops,
                                                         att_scores = tf.expand_dims(alphas, -1),
                                                         sequence_length=self.seq_len_ph, dtype=self.model_dtype,
                                                         scope="gru2")
                tf.summary.histogram('GRU2_Final_State', final_state2)

            inp = tf.concat([self.uid_batch_embedded, self.item_eb, self.item_his_eb_sum, self.item_eb * self.item_his_eb_sum, final_state2], 1)
            self.build_fcn_net(inp, use_dice=True)


class Model_DIN_V2_Gru_Vec_attGru(Model):
    def __init__(self, run_options, n_uid, n_mid, n_cat, EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE, use_negsampling=False):
        super(Model_DIN_V2_Gru_Vec_attGru, self).__init__(run_options, n_uid, n_mid, n_cat,
                                                          EMBEDDING_DIM, HIDDEN_SIZE, ATTENTION_SIZE,
                                                          use_negsampling)

        # RNN layer(-s)
        with tf.name_scope('rnn_1'):
            rnn_outputs, _ = dynamic_rnn(GRUCell(HIDDEN_SIZE), inputs=self.item_his_eb, max_iteration = self.options.max_rnn_while_loops,
                                         sequence_length=self.seq_len_ph, dtype=tf.float32,
                                         scope="gru1")
            tf.summary.histogram('GRU_outputs', rnn_outputs)

        # Attention layer
        with tf.name_scope('Attention_layer_1'):
            att_outputs, alphas = din_fcn_attention(self.item_eb, rnn_outputs, ATTENTION_SIZE, self.mask,
                                                    softmax_stag=1, stag='1_1', mode='LIST', return_alphas=True)
            tf.summary.histogram('alpha_outputs', alphas)

        with tf.name_scope('rnn_2'):
            rnn_outputs2, final_state2 = dynamic_rnn(VecAttGRUCell(HIDDEN_SIZE), inputs=rnn_outputs, max_iteration = self.options.max_rnn_while_loops,
                                                     att_scores = tf.expand_dims(alphas, -1),
                                                     sequence_length=self.seq_len_ph, dtype=tf.float32,
                                                     scope="gru2")
            tf.summary.histogram('GRU2_Final_State', final_state2)

        # inp = tf.concat([self.uid_batch_embedded, self.item_eb, final_state2, self.item_his_eb_sum], 1)
        inp = tf.concat([self.uid_batch_embedded, self.item_eb, self.item_his_eb_sum, self.item_eb * self.item_his_eb_sum, final_state2], 1)
        self.build_fcn_net(inp, use_dice=True)

2. 
