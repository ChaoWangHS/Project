# -*- coding: utf-8 -*-
"""
Spyder Editor

This is a temporary script file.
"""

import numpy as np
import tensorflow as tf
import config
import random
def unpickle(file):
  import _pickle as cPickle
  fo = open(file, 'rb')
  dict = cPickle.load(fo,encoding='latin1')
  fo.close()
  if 'data' in dict:
    dict['data'] = dict['data'].reshape((-1, 3, 32, 32)).swapaxes(1, 3).swapaxes(1, 2).reshape(-1, 32*32*3) / 256.

  return dict
def load_data_one(f):
  batch = unpickle(f)
  data = batch['data']
  labels = batch['labels']
  print ("Loading %s: %d" % (f, len(data)))
  return data, labels

def load_data(files, data_dir, label_count):
  data, labels = load_data_one(data_dir + '/' + files[0])
  for f in files[1:]:
    data_n, labels_n = load_data_one(data_dir + '/' + f)
    data = np.append(data, data_n, axis=0)
    labels = np.append(labels, labels_n, axis=0)
  labels = np.array([ [ float(i == label) for i in range(label_count) ] for label in labels ])
  return data, labels
def run_in_batch_avg(session, tensors, batch_placeholders, feed_dict={}, batch_size=200):                              
  res = [ 0 ] * len(tensors)                                                                                           
  batch_tensors = [ (placeholder, feed_dict[ placeholder ]) for placeholder in batch_placeholders ]                    
  total_size = len(batch_tensors[0][1])                                                                                
  batch_count = int((total_size + batch_size - 1) / batch_size)                                                             
  for batch_idx in range(batch_count):                                                                                
    current_batch_size = None                                                                                          
    for (placeholder, tensor) in batch_tensors:                                                                        
      batch_tensor = tensor[ batch_idx*batch_size : (batch_idx+1)*batch_size ]                                         
      current_batch_size = len(batch_tensor)                                                                           
      feed_dict[placeholder] = tensor[ batch_idx*batch_size : (batch_idx+1)*batch_size ]                               
    tmp = session.run(tensors, feed_dict=feed_dict)                                                                    
    res = [ r + t * current_batch_size for (r, t) in zip(res, tmp) ]                                                   
  return [ r / float(total_size) for r in res ]

#add dynamic mask
def add_dyprune(weights):
    crate = config.crate[weights.name[:-2]] #hyperpara C rate
    prune_mask = tf.Variable(tf.ones_like(weights),name=weights.name[:-2]+'mask', trainable=False)

    #calculate mask
    mean = tf.divide(tf.reduce_sum(tf.multiply(tf.abs(weights),prune_mask)),tf.reduce_sum(prune_mask))
    var = tf.multiply(weights,prune_mask)
    var = tf.square(var)
    mean_q = tf.square(mean)*tf.reduce_sum(prune_mask)
    var = tf.reduce_sum(var) - mean_q
    var = tf.divide(var,tf.reduce_sum(prune_mask))
    var = tf.sqrt(var)
    t1_lower = (mean+var*crate)*0.25 #hyperpara a
    t1_upper = (mean+var*crate)*0.45 #hyperpara b
    
    indicator_lower1 = tf.greater_equal(tf.abs(weights), tf.ones_like(weights) * t1_lower)    
    indicator_upper1 = tf.greater_equal(tf.abs(weights), tf.ones_like(weights) * t1_upper)
    indicator_matrix1 = tf.greater_equal(prune_mask, tf.zeros_like(weights))
    indicator_matrix1 = tf.logical_and(indicator_matrix1,indicator_lower1)
    indicator_matrix1 = tf.logical_or(indicator_matrix1,indicator_upper1)
    indicator_matrix1 = tf.to_float(indicator_matrix1)
    update = prune_mask.assign(indicator_matrix1)

    prune_fc = tf.multiply(weights, prune_mask)
    return prune_fc


def weight_variable(shape):
  initial = tf.truncated_normal(shape, stddev=0.01)   
  w = tf.Variable(initial)
  if w.name[:-2] in config.all_para: w = add_dyprune(w) #add dynamic mask
  return w

def bias_variable(shape):
  initial = tf.constant(0.01, shape=shape)
  return tf.Variable(initial)

def conv2d(input, in_features, out_features, kernel_size, with_bias=False):
  W = weight_variable([ kernel_size, kernel_size, in_features, out_features ])
  conv = tf.nn.conv2d(input, W, [ 1, 1, 1, 1 ], padding='SAME')
  if with_bias:
    return conv + bias_variable([ out_features ])
  return conv

def batch_activ_conv(current, in_features, out_features, kernel_size, is_training, keep_prob):
  current = tf.contrib.layers.batch_norm(current, scale=True, is_training=is_training, updates_collections=None)
  current = tf.nn.relu(current)
  current = conv2d(current, in_features, out_features, kernel_size)
  current = tf.nn.dropout(current, keep_prob)
  return current

def block(input, layers, in_features, growth, is_training, keep_prob):
  current = input
  features = in_features
  for idx in range(layers):
    tmp = batch_activ_conv(current, features, growth, 3, is_training, keep_prob)
    current = tf.concat((current, tmp),3)
    features += growth
  return current, features

def avg_pool(input, s):
  return tf.nn.avg_pool(input, [ 1, s, s, 1 ], [1, s, s, 1 ], 'VALID')

def get_dict(load_path):
    import pickle
    f2 = open(load_path,"rb")
    load_list = pickle.load(f2)
    f2.close()
    return load_list


def run_model(data, image_dim, label_count, depth):
  weight_decay = 1e-4
  layers = int((depth - 4) / 3)

  xs = tf.placeholder("float", shape=[None, image_dim])
  ys = tf.placeholder("float", shape=[None, label_count])
  lr = tf.placeholder("float", shape=[])
  keep_prob = tf.placeholder(tf.float32)
  is_training = tf.placeholder("bool", shape=[])
  
  current = tf.reshape(xs, [ -1, 32, 32, 3 ])
  current = conv2d(current, 3, 16, 3)
  
  current, features = block(current, layers, 16, 12, is_training, keep_prob)
  current = batch_activ_conv(current, features, features, 1, is_training, keep_prob)
  current = avg_pool(current, 2)
  current, features = block(current, layers, features, 12, is_training, keep_prob)
  current = batch_activ_conv(current, features, features, 1, is_training, keep_prob)
  current = avg_pool(current, 2)
  current, features = block(current, layers, features, 12, is_training, keep_prob)
  current = tf.contrib.layers.batch_norm(current, scale=True, is_training=is_training, updates_collections=None)
  current = tf.nn.relu(current)
  current = avg_pool(current, 8)
  
  final_dim = features
  current = tf.reshape(current, [ -1, final_dim ])
  Wfc = weight_variable([ final_dim, label_count ])
  bfc = bias_variable([ label_count ])
  ys_ = tf.nn.softmax( tf.matmul(current, Wfc) + bfc )
  cross_entropy = -tf.reduce_mean(ys * tf.log(ys_ + 1e-12))
  l2 = tf.add_n([tf.nn.l2_loss(var) for var in tf.trainable_variables()])

  
  correct_prediction = tf.equal(tf.argmax(ys_, 1), tf.argmax(ys, 1))
  accuracy = tf.reduce_mean(tf.cast(correct_prediction, "float"))
  
  para_dict={} #weights with mask
  for k in tf.global_variables():
      if k not in tf.contrib.framework.get_variables_by_suffix('Momentum'):
          para_dict[k.name[:-2]] = k
          
  para_toload={} #weights without mask
  for k in tf.global_variables():
    if k not in tf.contrib.framework.get_variables_by_suffix('Momentum'):
        if 'mask' not in k.name:            
            para_toload[k.name[:-2]] = k   

  A_assign=[] #group all undate operation
  for k in tf.get_default_graph().get_operations():
    if k.name.startswith('Assign'):
        A_assign.append(k.values()[0])
  updatemask=tf.group(*A_assign)
  
  
  train_step = tf.train.GradientDescentOptimizer(lr).minimize(cross_entropy)
  #train_step = tf.train.MomentumOptimizer(lr, 0.9, use_nesterov=True).minimize(cross_entropy + l2 * weight_decay)

  session = tf.InteractiveSession()
  batch_size = 64
  learning_rate = 0.1
  session.run(tf.global_variables_initializer())
  train_data, train_labels = data['train_data'], data['train_labels']
  batch_count = int(len(train_data) / batch_size)
  batches_data = np.split(train_data[:batch_count * batch_size], batch_count)
  batches_labels = np.split(train_labels[:batch_count * batch_size], batch_count)
  print ("Batch per epoch: ", batch_count)
  
  
  #set weights path
  load_path = 'modellog/weightonlypara93.ckpt'
  #normal save path  
  normal_savepath = 'dns2/dns222_%d.ckpt'
  #best result save path  
  best_savepath = 'dns3/densenetdns222_%d_%d.ckpt'
  
  maxepoch = 35 #maxepoch for DNS
  ##need config
  
  #load weights
  saver = tf.train.Saver(para_dict)
 # saver = tf.train.Saver(para_toload)
  saver.restore(session,load_path)#########################################
  
  #auto-change learning rate to converge quicker
  final_acc = 0.0
  #test_results = run_in_batch_avg(session, [ cross_entropy, accuracy ], [ xs, ys ],
 #   feed_dict = { xs: data['test_data'], ys: data['test_labels'], is_training: False, keep_prob: 1. })
#  print (test_results)
 # final_acc= test_results[1]
  
  sss=0
  count = 0
  saver = tf.train.Saver(para_dict)
  best_acc = 0.0
  for epoch in range(1, 1+300-sss):
    if epoch >= 150-sss: learning_rate = 0.01
    if epoch >= 225-sss: learning_rate = 0.001
    if epoch >= 275-sss: learning_rate = 0.0001
    if final_acc >= 0.77 :learning_rate = 0.01
    if final_acc >= 0.9 :learning_rate = 0.001
#    if final_acc >= 0.927 :learning_rate = 0.0001
    
    
    for batch_idx in range(batch_count):
        xs_, ys_ = batches_data[batch_idx], batches_labels[batch_idx]
        batch_res = session.run([ train_step, cross_entropy, accuracy ],
          feed_dict = { xs: xs_, ys: ys_, lr: learning_rate, is_training: True, keep_prob: 0.8 })
        
        #use prob function to control DNS
        #if 1/(1+0.01*epoch)>random.uniform(0,1) and (epoch<maxepoch) and (epoch % 2 !=0) and (batch_idx % 2 ==0):
        if 1/(1+0.01*epoch)>random.uniform(0,1) and (epoch<maxepoch) and (epoch % 2 !=0) and (batch_idx % 2 ==0):
            session.run(updatemask)
        if batch_idx % 100 == 0: 
            print (epoch, batch_idx, batch_res[1:])
           # print(np.sum(tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, "Variable_25mask:0")[0].eval()))
          #  print(np.sum(tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, "Variable_32mask:0")[0].eval()))
          
          
    saver.save(session, normal_savepath % epoch)
    test_results = run_in_batch_avg(session, [ cross_entropy, accuracy ], [ xs, ys ],
          feed_dict = { xs: data['test_data'], ys: data['test_labels'], is_training: False, keep_prob: 1. })
    print (epoch, batch_res[1:], test_results)
    
    #save the best result    
    final_acc= test_results[1]
    if best_acc < final_acc:
        count+=1
        best_acc = final_acc
        acc_num = int(final_acc*100000)
        saver.save(session, best_savepath % (acc_num,count))#####################################




data_dir = 'data'
image_size = 32
image_dim = image_size * image_size * 3
meta = unpickle(data_dir + '/batches.meta')
label_names = meta['label_names']
label_count = len(label_names)

train_files = [ 'data_batch_%d' % d for d in range(1, 6) ]
train_data, train_labels = load_data(train_files, data_dir, label_count)
pi = np.random.permutation(len(train_data))
train_data, train_labels = train_data[pi], train_labels[pi]
test_data, test_labels = load_data([ 'test_batch' ], data_dir, label_count)
print ("Train:", np.shape(train_data), np.shape(train_labels))
print ("Test:", np.shape(test_data), np.shape(test_labels))
data = { 'train_data': train_data,
  'train_labels': train_labels,
  'test_data': test_data,
  'test_labels': test_labels }

run_model(data, image_dim, label_count, 40)
