import os
import sys
import argparse
import optparse
import subprocess
import numpy as np
from Density_Ratio_discrete import Density_Ratio_discrete
from Q_learning import Q_learning
from environment import random_walk_2d, taxi
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import seaborn as sns
sns.set(style="white")


def roll_out(state_num, env, policy, num_trajectory, truncate_size):
	SASR = []
	total_reward = 0.0
	frequency = np.zeros(state_num)
	for i_trajectory in range(num_trajectory):
		state = env.reset()
		sasr = []
		for i_t in range(truncate_size):
			#env.render()
			p_action = policy[state, :]
			p_action = p_action / np.sum(p_action)
			action = np.random.choice(p_action.shape[0], 1, p = p_action)[0]
			next_state, reward = env.step(action)

			sasr.append((state, action, next_state, reward))
			frequency[state] += 1
			total_reward += reward
			#print env.state_decoding(state)
			#a = input()

			state = next_state
		SASR.append(sasr)
	return SASR, frequency, total_reward/(num_trajectory * truncate_size)

def train_density_ratio(SASR, policy0, policy1, den_discrete):
	for sasr in SASR:
		for state, action, next_state, reward in sasr:
			policy_ratio = policy1[state, action]/policy0[state, action]
			den_discrete.feed_data(state, next_state, policy_ratio)
	x, w = den_discrete.density_ratio_estimate()
	return x, w

def off_policy_evaluation_density_ratio(SASR, policy0, policy1, density_ratio):
	total_reward = 0.0
	self_normalizer = 0.0
	for sasr in SASR:
		for state, action, next_state, reward in sasr:
			policy_ratio = policy1[state, action]/policy0[state, action]
			total_reward += density_ratio[state] * policy_ratio * reward
			self_normalizer += density_ratio[state] * policy_ratio
	return total_reward / self_normalizer

def importance_sampling_estimator(SASR, policy0, policy1):
	mean_est_reward = 0.0
	for sasr in SASR:
		log_trajectory_ratio = 0.0
		total_reward = 0.0
		for state, action, next_state, reward in sasr:
			log_trajectory_ratio += np.log(policy1[state, action]) - np.log(policy0[state, action])
			total_reward += reward
		avr_reward = total_reward / len(sasr)
		mean_est_reward += avr_reward * np.exp(log_trajectory_ratio)
	mean_est_reward /= len(SASR)
	return mean_est_reward

def importance_sampling_estimator_stepwise(SASR, policy0, policy1):
	mean_est_reward = 0.0
	for sasr in SASR:
		step_log_pr = 0.0
		est_reward = 0.0
		for state, action, next_state, reward in sasr:
			step_log_pr += np.log(policy1[state, action]) - np.log(policy0[state, action])
			est_reward += np.exp(step_log_pr)*reward
		est_reward /= len(sasr)
		mean_est_reward += est_reward
	mean_est_reward /= len(SASR)
	return mean_est_reward

def weighted_importance_sampling_estimator(SASR, policy0, policy1):
	total_rho = 0.0
	est_reward = 0.0
	for sasr in SASR:
		total_reward = 0.0
		log_trajectory_ratio = 0.0
		for state, action, next_state, reward in sasr:
			log_trajectory_ratio += np.log(policy1[state, action]) - np.log(policy0[state, action])
			total_reward += reward
		avr_reward = total_reward / len(sasr)
		trajectory_ratio = np.exp(log_trajectory_ratio)
		total_rho += trajectory_ratio
		est_reward += trajectory_ratio * avr_reward

	avr_rho = total_rho / len(SASR)
	return est_reward / avr_rho/ len(SASR)

def weighted_importance_sampling_estimator_stepwise(SASR, policy0, policy1):
	Log_policy_ratio = []
	REW = []
	for sasr in SASR:
		log_policy_ratio = []
		rew = []
		for state, action, next_state, reward in sasr:
			log_pr = np.log(policy1[state, action]) - np.log(policy0[state, action])
			if log_policy_ratio:
				log_policy_ratio.append(log_pr + log_policy_ratio[-1])
			else:
				log_policy_ratio.append(log_pr)
			rew.append(reward)
		Log_policy_ratio.append(log_policy_ratio)
		REW.append(rew)
	est_reward = 0.0
	rho = np.exp(Log_policy_ratio)
	#print 'rho shape = {}'.format(rho.shape)
	REW = np.array(REW)
	for i in range(REW.shape[0]):
		est_reward += np.mean(rho[i]/np.mean(rho, axis = 0) * REW[i])
	return est_reward/REW.shape[0]


def Q_learning(env, num_trajectory, truncate_size, temperature = 2.0):
	agent = Q_learning(n_state, n_action, 0.01, 0.99)

	state = env.reset()
	for k in range(20):
		print 'Training for episode {}'.format(k)
		for i in range(50):
			for j in range(5000):
				action = agent.choose_action(state, temperature)
				next_state, reward = env.step(action)
				agent.update(state, action, next_state, reward)
				state = next_state
		pi = agent.get_pi(temperature)
		np.save('taxi-policy/pi{}.npy'.format(k), pi)
		SAS, f, avr_reward = roll_out(n_state, env, pi, num_trajectory, truncate_size)
		print 'Episode {} reward = {}'.format(k, avr_reward)
		heat_map(length, f, env, 'heatmap/pi{}.pdf'.format(k))

def heat_map(length, f, env, filename):
	p_matrix = np.zeros([length, length], dtype = np.float32)
	for state in range(env.n_state):
		x,y,_,_ = env.state_decoding(state)
		#x,y = env.state_decoding(state)
		p_matrix[x,y] = f[state]
	p_matrix = p_matrix / np.sum(p_matrix)
	
	sns.heatmap(p_matrix, cmap="YlGnBu")#, vmin = 0.0, vmax = 0.07)
	ppPDF = PdfPages(filename)
	ppPDF.savefig()
	ppPDF.close()
	plt.clf()

def model_based(n_state, n_action, SASR, pi):
	T = np.zeros([n_state, n_action, n_state], dtype = np.float32)
	R = np.zeros([n_state, n_action], dtype = np.float32)
	R_count = np.zeros([n_state, n_action], dtype = np.int32)
	for sasr in SASR:
		for state, action, next_state, reward in sasr:
			T[state, action, next_state] += 1
			R[state, action] += reward
			R_count[state, action] += 1
	d0 = np.zeros([n_state, 1], dtype = np.float32)

	for state in SASR[:,0,0].flat:
		d0[state, 0] += 1.0
	t = np.where(R_count > 0)
	t0 = np.where(R_count == 0)
	R[t] = R[t]/R_count[t]
	R[t0] = np.mean(R[t])
	T = T + 1e-9	# smoothing
	T = T/np.sum(T, axis = -1)[:,:,None]
	Tpi = np.zeros([n_state, n_state])
	for state in range(n_state):
		for next_state in range(n_state):
			for action in range(n_action):
				Tpi[state, next_state] += T[state, action, next_state] * pi[state, action]
	dt = d0/np.sum(d0)
	dpi = np.zeros([n_state, 1], dtype = np.float32)
	truncate_size = SASR.shape[1]
	for i in range(truncate_size):
		dpi += dt
		if i < 50:
			dt = np.dot(Tpi.T,dt)
	dpi /= truncate_size
	Rpi = np.sum(R * pi, axis = -1)
	return np.sum(dpi.reshape(-1) * Rpi)

def run_experiment(n_state, n_action, SASR, pi0, pi1):
	den_discrete = Density_Ratio_discrete(n_state)
	x, w = train_density_ratio(SASR, pi0, pi1, den_discrete)
	x = x.reshape(-1)
	w = w.reshape(-1)

	est_DENR = off_policy_evaluation_density_ratio(SASR, pi0, pi1, w)
	est_naive_average = np.mean(SASR[:,:,3])
	est_IST = importance_sampling_estimator(SASR, pi0, pi1)
	est_ISS = importance_sampling_estimator_stepwise(SASR, pi0, pi1)
	est_WIST = weighted_importance_sampling_estimator(SASR, pi0, pi1)
	est_WISS = weighted_importance_sampling_estimator_stepwise(SASR, pi0, pi1)
	est_model_based = model_based(n_state, n_action, SASR, pi1)

	return est_DENR, est_naive_average, est_IST, est_ISS, est_WIST, est_WISS, est_model_based
	#return est_DENR

if __name__ == '__main__':
	length = 5
	NT = [30, 50, 100, 200, 400, 600, 800]
	TS = [50, 100, 200, 600, 1000, 1500]
	BP = [0, 1, 2, 3, 4]
	RATIO = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

	num_trajectory = 100
	truncate_size = 400
	behavior_ID = 4
	target_ID = 5
	env = taxi(length)
	n_state = env.n_state
	n_action = env.n_action
	
	# parser = argparse.ArgumentParser(description='Create SARS file for taxi environment')
	# parser.add_argument('expID', type = int)
	# parser.add_argument('repeat_time', type = int)
	# args = parser.parse_args()

	# expID = args.expID
	# repeat_time = args.repeat_time
	# seed_base = repeat_time * expID
	
	# for j in range(9):
	# 	pi0 = np.load('taxi-policy/pi18.npy')
	# 	pi1 = np.load('taxi-policy/pi19.npy')
	# 	pi = RATIO[j] * pi1 + (1-RATIO[j]) * pi0
	# 	for i in range(repeat_time):
	# 		np.random.seed(i + seed_base)
	# 		SASR, _, _ = roll_out(n_state, env, pi, num_trajectory, truncate_size)
	# 		np.save('/home/utcsaiml/data/taxi/SASR_r={}_seed={}.npy'.format(RATIO[j], i + seed_base), SASR)
	# 		# np.save('temp/SASR_pi{}_seed={}.npy'.format(j, i + seed_base), SASR)

	# for j in range(6):
	# 	pi = np.load('taxi-policy/pi{}.npy'.format(14 + j))
	# 	for i in range(repeat_time):
	# 		np.random.seed(i + seed_base)
	# 		SASR, _, true_reward = roll_out(n_state, env, pi, num_trajectory, truncate_size)
	# 		#np.save('/home/utcsaiml/data/taxi/SASR_pi{}_seed={}.npy'.format(j, i + seed_base), SASR)
	# 		np.save('temp/SASR_pi{}_seed={}.npy'.format(j, i + seed_base), SASR)
	
	pi_target = np.load('taxi-policy/pi19.npy')
	parser = argparse.ArgumentParser(description='taxi environment')
	parser.add_argument('expID', type = int)
	args = parser.parse_args()

	# COMBINATION = []
	# for nt in NT:
	# 	COMBINATION.append((nt, truncate_size, behavior_ID))

	# for ts in TS:
	# 	if ts == truncate_size: continue
	# 	COMBINATION.append((num_trajectory, ts, behavior_ID))

	# for bp in BP:
	# 	COMBINATION.append((num_trajectory, truncate_size, bp))

	# nt, ts, bp = COMBINATION[args.expID]
	
	# print('average case: nt = {}, ts = {}, bp = {}'.format(nt, ts, bp))
	#pi_behavior = np.load('taxi-policy/pi{}.npy'.format(14 + bp))

	alpha = RATIO[args.expID]
	print('mixed_ratio = {}'.format(alpha))
	nt = num_trajectory
	ts = truncate_size
	pi_behavior = np.load('taxi-policy/pi18.npy')

	pi_behavior = alpha * pi_target + (1-alpha) * pi_behavior
	
	res = np.zeros((8, 200), dtype = np.float32)
	#res = np.load('reward_result/NT={}_TS={}_BP={}.npy'.format(nt, ts, bp))
	for k in range(200):
		SASR0 = np.load('/home/utcsaiml/data/taxi/SASR_r={}_seed={}.npy'.format(alpha, k))
		# SASR0 = np.load('/home/utcsaiml/data/taxi/SASR_pi{}_seed={}.npy'.format(bp, k))
		# SASR0 = np.load('temp/SASR_pi{}_seed={}.npy'.format(bp, k))
		SASR0 = SASR0[:nt, :ts]
		res[1:,k] = run_experiment(n_state, n_action, SASR0, pi_behavior, pi_target)
		# res[1,k] = run_experiment(n_state, n_action, SASR0, pi_behavior, pi_target)

		SASR = np.load('/home/utcsaiml/data/taxi/SASR_pi5_seed={}.npy'.format(k))
		#SASR = np.load('temp/SASR_pi5_seed={}.npy'.format(k))
		SASR = SASR[:nt, :ts]
		res[0, k] = np.mean(SASR[:,:,3])
		print('seed = {}, est_rewards = {}'.format(k, res[:,k]))
		sys.stdout.flush()
	np.save('reward_result/mixed_ratio={}.npy'.format(alpha), res)
	