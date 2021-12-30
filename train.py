import numpy as np
import matplotlib.pyplot as plt
import os
import torch
import torchvision
import torchvision.transforms as transforms
import torch.optim as optim
from torch.autograd import Variable
import torch.nn as nn
import torch.nn.functional as F
import os.path
import torch.nn.parallel
import torch.utils.data as data
import torchvision.datasets as datasets
import torchvision.models as models
from tqdm import tqdm
from matplotlib import gridspec 
import matplotlib.pyplot as plt

from misc import *

def train(G, D, optim_G, optim_D, dataset, configs):#iter_num = 100, batch_size = 30):
    
    if configs.use_tensorboard:
        from tensorboardX import SummaryWriter

        if not os.path.exists(configs.log_dir):
            os.mkdir(configs.log_dir)
        summary = SummaryWriter(logdir = configs.log_dir)

    
    device = f'cuda:{configs.main_gpu:d}' if torch.cuda.is_available() else 'cpu'
    
    if torch.cuda.is_available():
        G.to(device)
        D.to(device)

        latent_fixed = torch.randn((3, configs.latent_dim)).to(device)
    
    data_iter = iter(dataset)
    
    g_lr = configs.lr
    d_lr = configs.lr
    
        
    for i in tqdm(range(configs.iter_num)):
        
        reals = next(data_iter)

        if torch.cuda.is_available():
            reals = reals[0].to(device)
            latents = torch.randn((configs.batch_size, configs.latent_dim)).to(device)
        
        # discriminator
        
        # for real
        d_real_out = D(reals)
        loss_real = -torch.mean(d_real_out)
        
        # for fake
        fake_img = G(latents)
        d_fake_out = D(fake_img.detach())
        loss_fake = torch.mean(d_fake_out)
        
        
        # grad penalty
        alpha = torch.rand(reals.size(0), 1, 1, 1).to(device)
        x_hat = (alpha * reals.data + (1- alpha) * fake_img.data).requires_grad_(True)
        out = D(x_hat)
        d_loss_gp = gradient_penalty(out, x_hat, device)
        
        d_loss = loss_real + loss_fake + d_loss_gp * configs.lambda_gp
        
        G.zero_grad()
        D.zero_grad()
        d_loss.backward()
        optim_D.step()
        
        loss = {}
            
        # log for tensorboard
        summary.add_scalar('D/loss_real', loss_real.item(), i)
        summary.add_scalar('D/loss_fake', loss_fake.item(), i)
        summary.add_scalar('D/d_loss', d_loss.item(), i)
        summary.add_scalar('D/loss_gp', d_loss_gp.item(), i)

        loss['D/loss_real'] = loss_real.item()
        loss['D/loss_fake'] = loss_fake.item()
        loss['D/d_loss'] = d_loss.item()
        
        # generator
        if (i+1) % configs.n_critic == 0:
            
            latents = torch.randn((configs.batch_size, configs.latent_dim)).to(device)

            gen_out = G(latents)
            d_out = D(gen_out)

            g_loss = -torch.mean(d_out)

            G.zero_grad()
            g_loss.backward()
            optim_G.step()
            
            # log for tensorboard
            summary.add_scalar('G/loss_fake', loss_fake.item(), i)
            
            loss['G/loss_fake'] = g_loss.item()
        
        # misc
        with torch.no_grad():

            if i % 100 == 0:
                print(f'iter{i:d}')
                gs = gridspec.GridSpec(1, latent_fixed.size(0), wspace = 0.02, hspace = 0.1)
                plt.tight_layout()
                plt.figure(figsize = (3*latent_fixed.size(0), 3))
                
                imgs = G(latent_fixed.to(device))
                
                for j in range(latent_fixed.size(0)):
                    plt.subplot(gs[0,j])
                    plt.imshow(minmax(imgs[j].detach().cpu()).permute(1,2,0))
                    plt.axis('off')
                    
                plt.savefig(configs.image_name)
                
                # print(f'D/d_loss: {loss['D/d_loss']:.2f}, D/loss_real: {loss['D/loss_real']:.2f}, D/loss_fake: {loss['D/loss_fake']:.2f}, G/loss_fake: {loss['G/loss_fake']:.2f}')

        # Save model checkpoints.
        if not os.path.exists(f'./checkpoint{configs.main_gpu:d}'):
            os.mkdir(f'./checkpoint{configs.main_gpu:d}')
        if (i+1) % 10000 == 0:
            G_path = os.path.join(f'./checkpoint{configs.main_gpu:d}', '{}-G.ckpt'.format(i+1))
            D_path = os.path.join(f'./checkpoint{configs.main_gpu:d}', '{}-D.ckpt'.format(i+1))

        # learning rate decay
        
        if i >= 10000 and i % 1000 == 0:
            g_lr -= (g_lr / float(100000))
            d_lr -= (d_lr / float(100000))
            for p_G, p_D in zip(optim_G.param_groups, optim_D.param_groups):
                p_G['lr'] = g_lr
                p_D['lr'] = d_lr