﻿import argparse, random
from tqdm import tqdm

import torch

import options.options as option
from utils import util
import os
from solvers import create_solver
from data import create_dataloader
from data import create_dataset

os.environ["CUDA_VISIBLE_DEVICES"] = "6,7"

def main():
    parser = argparse.ArgumentParser(description='Train Super Resolution Models')
    #	parser.add_argument('-opt', type=str, required=True, help='Path to options JSON file.')
    #	opt = option.parse(parser.parse_args().opt)
    opt = option.parse('options/train/train_EDSR_v3.json')


    # random seed
    seed = opt['solver']['manual_seed']
    if seed is None: seed = random.randint(1, 10000)
    print("===> Random Seed: [%d]"%seed)
    random.seed(seed)
    torch.manual_seed(seed)

    # create train and val dataloader
    loader_list =[]
    for phase, dataset_opt in sorted(opt['datasets'].items()):
        if phase == 'train':
            train_set = create_dataset(dataset_opt)
            train_loader = create_dataloader(train_set, dataset_opt)
            print('===> Train Dataset: %s   Number of images: [%d]' % (train_set.name(), len(train_set)))
            if train_loader is None: raise ValueError("[Error] The training data does not exist")

        elif phase.find('val') == 0:
            val_set = create_dataset(dataset_opt)
            val_loader = create_dataloader(val_set, dataset_opt)
            loader_list.append(val_loader)
            print('===> Val Dataset: %s   Number of images: [%d]' % (val_set.name(), len(val_set)))
        
        else:
            raise NotImplementedError("[Error] Dataset phase [%s] in *.json is not recognized." % phase)

    solver = create_solver(opt)
    scale = opt['scale']
    model_name = opt['networks']['which_model'].upper()
    print(model_name)

    print('===> Start Train')
    print("==================================================")

    solver_log = solver.get_current_log()

    NUM_EPOCH = int(opt['solver']['num_epochs'])
    start_epoch = solver_log['epoch']

    print("Method: %s || Scale: %d || Epoch Range: (%d ~ %d)"%(model_name, scale, start_epoch, NUM_EPOCH))

    for epoch in range(start_epoch, NUM_EPOCH + 1):
        print('\n===> Training Epoch: [%d/%d]...  Learning Rate: %f'%(epoch,
                                                                      NUM_EPOCH,
                                                                      solver.get_current_learning_rate()))

        # Initialization
        solver_log['epoch'] = epoch

        # Train model
        train_loss_list = []
        with tqdm(total=len(train_loader), desc='Epoch: [%d/%d]'%(epoch, NUM_EPOCH), miniters=1) as t:
            for iter, batch in enumerate(train_loader):
                solver.feed_data(batch)
                iter_loss = solver.train_step()
                batch_size = batch['LR'].size(0)
                train_loss_list.append(iter_loss*batch_size)
                t.set_postfix_str("Batch Loss: %.4f" % iter_loss)
                t.update()

        solver_log['records']['train_loss'].append(sum(train_loss_list)/len(train_set))
        solver_log['records']['lr'].append(solver.get_current_learning_rate())

        print('\nEpoch: [%d/%d]   Avg Train Loss: %.6f' % (epoch,
                                                    NUM_EPOCH,
                                                    sum(train_loss_list)/len(train_set)))

        print('===> Validating...',)

        for i, val_loader in enumerate(loader_list):
            val_loss_list = []
            psnr_list = []
            ssim_list = []
            for iter, batch in enumerate(val_loader):
                solver.feed_data(batch)
                iter_loss = solver.test()
                val_loss_list.append(iter_loss)

                # calculate evaluation metrics
                visuals = solver.get_current_visual()
                psnr, ssim = util.calc_metrics(visuals['SR'], visuals['HR'], crop_border=scale, test_Y=True)
                psnr_list.append(psnr)
                ssim_list.append(ssim)

                if opt["save_image"]:
                    solver.save_current_visual(epoch, iter)
            if 'val_loss_{}'.format(i) not in solver_log['records']:
                solver_log['records']['val_loss_{}'.format(i)]= []
            if 'psnr_{}'.format(i) not in solver_log['records']:
                solver_log['records']['psnr_{}'.format(i)] = []
            if 'ssim_{}'.format(i) not in solver_log['records']:
                solver_log['records']['ssim_{}'.format(i)] = []
            
            solver_log['records']['val_loss_{}'.format(i)].append(sum(val_loss_list)/len(val_loss_list))
            solver_log['records']['psnr_{}'.format(i)].append(sum(psnr_list)/len(psnr_list))
            solver_log['records']['ssim_{}'.format(i)].append(sum(ssim_list)/len(ssim_list))

        # record the best epoch
        epoch_is_best = False
        # print(solver_log['records']['psnr_5'])
        if solver_log['best_pred'] < solver_log['records']['psnr_5'][epoch-1]:
            solver_log['best_pred'] = solver_log['records']['psnr_5'][epoch-1]
            epoch_is_best = True
            solver_log['best_epoch'] = epoch


        print("[%s] PSNR: %.2f   SSIM: %.4f   Loss: %.6f   Best PSNR: %.2f in Epoch: [%d]" % (val_set.name(),
                                                                                              solver_log['records']['psnr_5'][epoch-1],
                                                                                              solver_log['records']['ssim_5'][epoch-1],
                                                                                              solver_log['records']['val_loss_5'][epoch-1],
                                                                                              solver_log['best_pred'],
                                                                                              solver_log['best_epoch']))
                                                                                                                                                                       

        solver.set_current_log(solver_log)
        solver.save_checkpoint(epoch, epoch_is_best)
        solver.save_current_log()

        # update lr
        solver.update_learning_rate(epoch)

    print('===> Finished !')


if __name__ == '__main__':
    main()