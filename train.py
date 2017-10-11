import numpy as np
import sys
import math
import operator
import csv
import glob,os
import xlrd
import cv2
import pandas as pd

from sklearn.svm import SVC
from collections import Counter
from sklearn.metrics import confusion_matrix
import scipy.io as sio
import pydot, graphviz

from keras.models import Sequential, Model
from keras.layers import LSTM, Dense, TimeDistributed
from keras.utils import np_utils, plot_model
from keras import metrics
from keras import backend as K
from keras.models import model_from_json
from keras.layers import Dense, Dropout, Flatten, Activation
from keras.layers import Conv2D, MaxPooling2D
from keras.preprocessing.sequence import pad_sequences
import keras

import theano

from labelling import collectinglabel
from reordering import readinput
from evaluationmatrix import fpr
from utilities import Read_Input_Images, get_subfolders_num, data_loader_with_LOSO, label_matching, duplicate_channel
from models import VGG_16, LSTM_KAIST, CNN_KAIST

############## Path Preparation ######################
dB = "CASME2_TIM"
workplace = '/media/ice/OS/Datasets/' + dB + "/"
inputDir = '/media/ice/OS/Datasets/' + dB + "/" + dB + "/" 
######################################################

############# Reading Labels from XCEL ########################
wb=xlrd.open_workbook('/media/ice/OS/Datasets/CASME2_label_Ver_2.xls')
ws=wb.sheet_by_index(0)    
colm=ws.col_slice(colx=0,start_rowx=1,end_rowx=None)
iD=[str(x.value) for x in colm]
colm=ws.col_slice(colx=1,start_rowx=1,end_rowx=None)
vidName=[str(x.value) for x in colm]
colm=ws.col_slice(colx=6,start_rowx=1,end_rowx=None)
expression=[str(x.value) for x in colm]
table=np.transpose(np.array([np.array(iD),np.array(vidName),np.array(expression)],dtype=str))
# print(table)
###############################################################



###################### Samples to-be ignored ##########################
# ignored due to:
# 1) no matching label.
# 2) fear, sadness are excluded due to too little data, see CASME2 paper for more
IgnoredSamples = ['sub09/EP13_02/','sub09/EP02_02f/','sub10/EP13_01/','sub17/EP15_01/',
					'sub17/EP15_03/','sub19/EP19_04/','sub24/EP10_03/','sub24/EP07_01/',
					'sub24/EP07_04f/','sub24/EP02_07/','sub26/EP15_01/']
listOfIgnoredSamples=[]
for s in range(len(IgnoredSamples)):
	if s==0:
		listOfIgnoredSamples=[inputDir+IgnoredSamples[s]]
	else:
		listOfIgnoredSamples.append(inputDir+IgnoredSamples[s])
### Get index of samples to be ignored in terms of subject id ###
IgnoredSamples_index = np.empty([0])
for item in IgnoredSamples:
	item = item.split('sub', 1)[1]
	item = int(item.split('/', 1)[0]) - 1 
	IgnoredSamples_index = np.append(IgnoredSamples_index, item)

#######################################################################

############## Variables ###################
spatial_size = 224
r=w=spatial_size
resizedFlag=1
subjects=26
samples=246
n_exp=5
VidPerSubject = get_subfolders_num(inputDir, IgnoredSamples_index)
timesteps_TIM = 10
data_dim = r * w
pad_sequence = 10
############################################

################## Clearing labels.txt ################
os.remove(workplace + "Classification/CASME2_TIM_label.txt")
#######################################################

############ Reading Images and Labels ################
SubperdB = Read_Input_Images(inputDir, listOfIgnoredSamples, dB, resizedFlag, table, workplace, spatial_size)
print("Loaded Images into the tray...")
labelperSub = label_matching(workplace, dB, subjects, VidPerSubject)
print("Loaded Labels into the tray...")
#######################################################


########### Model #######################
kaist_cnn = CNN_KAIST()
kaist_cnn.compile(loss='mean_absolute_error',optimizer='Adam',metrics=[metrics.categorical_accuracy])

kaist_lstm = LSTM_KAIST()
kaist_lstm.compile(loss='categorical_crossentropy', optimizer='Adam', metrics=[metrics.categorical_accuracy])

temporal_model = Sequential()
temporal_model.add(LSTM(2622, return_sequences=True, input_shape=(10, 2622)))
temporal_model.add(LSTM(1000, return_sequences=False))
temporal_model.add(Dense(128, activation='sigmoid'))
temporal_model.add(Dense(5, activation='sigmoid'))
temporal_model.compile(loss='categorical_crossentropy', optimizer='Adam', metrics=[metrics.categorical_accuracy])
#########################################

################# Pretrained Model ###################
vgg_model = VGG_16('VGG_Face_Deep_16.h5')
vgg_model.compile(lr=0.0001, loss='categorical_crossentropy', optimizer='Adam', metrics=[metrics.categorical_accuracy])
plot_model(vgg_model, to_file='model.png', show_shapes=True)

######################################################

########### Training Process ############
# Todo:
# 1) LOSO (done)
# 2) call model (done)
# 3) saving model architecture
# 4) Saving Checkpoint
# 5) make prediction (done)
tot_mat = np.zeros((n_exp,n_exp))
for sub in range(subjects):
	cat_path = tensorboard_path + str(sub) + "/"
	os.mkdir(cat_path)
	tbCallBack = keras.callbacks.TensorBoard(log_dir=cat_path, write_graph=True)

	cat_path2 = tensorboard_path + str(sub) + "spat/"
	os.mkdir(cat_path2)
	tbCallBack2 = keras.callbacks.TensorBoard(log_dir=cat_path2, write_graph=True)

	image_label_mapping = np.empty([0])

	Train_X, Train_Y, Test_X, Test_Y, Test_Y_gt = data_loader_with_LOSO(sub, SubperdB, labelperSub, subjects)

	# Rearrange Training labels into a vector of images, breaking sequence
	Train_X_spatial = Train_X.reshape(Train_X.shape[0]*10, r, w, 1)
	Test_X_spatial = Test_X.reshape(Test_X.shape[0]* 10, r, w, 1)

	# Extend Y labels 10 fold, so that all images have labels
	Train_Y_spatial = np.repeat(Train_Y, 10, axis=0)
	# print(Train_Y_spatial.shape)
	# Train_Y_spatial = Train_Y_spatial.reshape(int(Train_Y_spatial.shape[0]/5), 5)
	Test_Y_spatial = np.repeat(Test_Y, 10, axis=0)
	# Test_Y_spatial = Test_Y_spatial.reshape(int(Test_Y_spatial.shape[0]/5), 5)

	

	# Duplicate channel of input image
	Train_X_spatial = duplicate_channel(Train_X_spatial)
	Test_X_spatial = duplicate_channel(Test_X_spatial)
	

	# print ("Train_X_shape: " + str(np.shape(Train_X_spatial)))
	# print ("Train_Y_shape: " + str(np.shape(Train_Y_spatial)))
	# print ("Test_X_shape: " + str(np.shape(Test_X_spatial)))	
	# print ("Test_Y_shape: " + str(np.shape(Test_Y_spatial)))	
	# print(Train_X_spatial)
	##################### VGG FACE 16 #########################

		

	X = Train_X_spatial.reshape(Train_X_spatial.shape[0], r, w, 3)
	y = Train_Y_spatial.reshape(Train_Y_spatial.shape[0], 5)

	test_X = Test_X_spatial.reshape(Test_X_spatial.shape[0], r, w, 3)
	test_y = Test_Y_spatial.reshape(Test_Y_spatial.shape[0], 5)
	# print ("Train_X_shape: " + str(np.shape(X)))
	# print ("Train_Y_shape: " + str(np.shape(y)))

	# output = new_vgg_face_16.fit(X, y, batch_size=32, epochs=1, shuffle=True )
	# tbCallBack = keras.callbacks.TensorBoard(log_dir='./tensorboard', batch_size=32, write_graph=True)
	vgg_model.fit(X, y, batch_size=48, epochs=10, shuffle=True, callbacks=[tbCallBack2])
	# vgg_model.fit(X, y, batch_size=48, epochs=10, shuffle=True)

	model = Model(inputs=vgg_model.input, outputs=vgg_model.layers[36].output)
	output = model.predict(X)
	# print(output.shape)


	###########################################################

	####################### Temporal Encoder ###########################
	features = output.reshape(int(output.shape[0]/10), 10, output.shape[1])
	# print(features.shape)
	temporal_model.fit(features, Train_Y, batch_size = 32, epochs=10, callbacks=[tbCallBack])
	# temporal_model.fit(features, Train_Y, batch_size = 32, epochs=10)

	####################################################################

	####################### Preliminary Evaluation ######################
	output = model.predict(test_X)
	features = output.reshape(int(output.shape[0]/10), 10, output.shape[1])
	output = temporal_model.predict(features)
	print(output)
	#####################################################################

	################### Formal Evaluation ############
	predict=temporal_model.predict_classes(features)
	print (predict)
	print (Test_Y_gt)	

	ct=confusion_matrix(Test_Y_gt,predict)
	# check the order of the CT
	order=np.unique(np.concatenate((predict,Test_Y_gt)))
	
	#create an array to hold the CT for each CV
	mat=np.zeros((n_exp,n_exp))
	#put the order accordingly, in order to form the overall ConfusionMat
	for m in range(len(order)):
		for n in range(len(order)):
			mat[int(order[m]),int(order[n])]=ct[m,n]
		   
	tot_mat=mat+tot_mat
	# write each CT of each CV into .txt file
	if not os.path.exists(workplace+'Classification/'+'Result/'+dB+'/'):
		os.mkdir(workplace+'Classification/'+ 'Result/'+dB+'/')
		
	with open(workplace+'Classification/'+ 'Result/'+dB+'/sub_CT.txt','a') as csvfile:
			thewriter=csv.writer(csvfile, delimiter=' ')
			thewriter.writerow('Sub ' + str(sub+1))
			thewriter=csv.writer(csvfile,dialect=csv.excel_tab)
			for row in ct:
				thewriter.writerow(row)
			thewriter.writerow(order)
			thewriter.writerow('\n')
			
	if sub==subjects-1:
			# compute the accuracy, F1, P and R from the overall CT
			microAcc=np.trace(tot_mat)/np.sum(tot_mat)
			[f1,p,r]=fpr(tot_mat,n_exp)

			# save into a .txt file
			with open(workplace+'Classification/'+ 'Result/'+dB+'/final_CT.txt','w') as csvfile:
				thewriter=csv.writer(csvfile,dialect=csv.excel_tab)
				for row in tot_mat:
					thewriter.writerow(row)
					
				thewriter=csv.writer(csvfile, delimiter=' ')
				thewriter.writerow('micro:' + str(microAcc))
				thewriter.writerow('F1:' + str(f1))
				thewriter.writerow('Precision:' + str(p))
				thewriter.writerow('Recall:' + str(r))			