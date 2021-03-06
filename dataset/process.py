import os
import glob
import argparse
import cv2
import numpy as np
import dlib

from mtcnn.mtcnn import MTCNN

class MirrorPadding:
    def __init__(self, landmarks_dat, using_gpu=False):
        self.detector = MTCNN('mtcnn/model/model.ckpt', using_gpu)
        self.predictor = dlib.shape_predictor(landmarks_dat)

    def padding(self, img):
        h, w = img.shape[:2]
        r = np.sqrt(h ** 2 + w ** 2) / 2
        res_h = r - h / 2
        res_w = r - w / 2
        
        tmp = np.copy(img)
        for i in range(int(np.ceil(res_h / h * 2)) + 1):
            if i % 4 == 0:
                tmp = np.concatenate((tmp, np.flip(img, 0)), 0)
            elif i % 4 == 1:        
                tmp = np.concatenate((np.flip(img, 0), tmp), 0)
            elif i % 4 == 2:
                tmp = np.concatenate((tmp, img), 0)
            elif i % 4 == 3:
                tmp = np.concatenate((img, tmp), 0)
        if np.ceil(res_h / h * 2 + 1) % 2 == 0:
            img = tmp
        else:
            img = np.roll(tmp, int(h / 2), axis=0)
        stride_h = int((np.ceil(res_h / h * 2) + 1) * h / 2)

        tmp = np.copy(img)
        for i in range(int(np.ceil(res_w / w * 2) + 1)):
            if i % 4 == 0:
                tmp = np.concatenate((tmp, np.flip(img, 1)), 1)
            elif i % 4 == 1:
                tmp = np.concatenate((np.flip(img, 1), tmp), 1)
            elif i % 4 == 2:
                tmp = np.concatenate((tmp, img), 1)
            elif i % 4 == 3:
                tmp = np.concatenate((img, tmp), 1)
        if np.ceil(res_w / w * 2 + 1) % 2 == 0:
            img = tmp
        else:
            img = np.roll(tmp, int(w / 2), axis=1)
        stride_w = int((np.ceil(res_w / w * 2) + 1) * w / 2)

        raw = img[stride_h:stride_h + h, stride_w:stride_w + w, :]
        f = int(max(h, w) / 10)
        img = cv2.blur(img, (f, f))
        img[stride_h:stride_h + h, stride_w:stride_w + w, :] = raw
        return img

    def get_landmarks(self, img):
        h, w = img.shape[:2]
        r = max(h, w) / 1000
        resized = cv2.resize(img, (int(w / r), int(h / r)),
                         interpolation=cv2.INTER_CUBIC)
        resized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

        try:
            bbs = self.detector.detect(resized)[0]
        except:
            return None

        if len(bbs) != 1:
            return None

        left, top, right, bottom = [int(i * r) for i in bbs[0][:4]]

        rect = dlib.rectangle(left=left, top=top, right=right, bottom=bottom)
        landmarks = np.float32([(p.x, p.y) for p in self.predictor(img, rect).parts()])
        return landmarks

    def detect(self, img, mirror):
        raw_h, raw_w = img.shape[:2]
        h, w = mirror.shape[:2]
        
        landmarks = self.get_landmarks(img)
        if landmarks is None:
            return None

        delta_h = (h - raw_h) / 2
        delta_w = (w - raw_w) / 2
        landmarks[:, 1] += delta_h
        landmarks[:, 0] += delta_w

        e0 = (landmarks[36] + landmarks[39]) / 2 # right eye
        e1 = (landmarks[42] + landmarks[45]) / 2 # left eye
        m0 = landmarks[48] # right mouse
        m1 = landmarks[54] # left mouse

        # is frontal or not
        threshold = 3.0
        center = landmarks[30]
        right = abs(center[0] - e0[0])
        left = abs(e1[0] - center[0])
        score = max(left, right) / min(left, right)
        if score > threshold:
            return None

        x = e1 - e0
        y = (e0 + e1) / 2 - (m0 + m1) / 2
        c = (e0 + e1) / 2 - 0.1 * y # center
        s = max(4 * np.linalg.norm(x, ord=1), 3.6 * np.linalg.norm(y, ord=1)) # size

        r = -np.arctan(x[1] / x[0])
        R = np.array([[np.cos(r), -np.sin(r)], [np.sin(r), np.cos(r)]])
        c = c - [w / 2, h / 2] # translation
        c = np.dot(R, c) + [w / 2, h / 2] # rotation and translation

        left = max(0, int(c[0] - s / 2))
        right = min(w, int(c[0] + s / 2))
        top = max(0, int(c[1] - s / 2))
        bottom = min(h, int(c[1] + s / 2))

        r = -r * 180 / np.pi
        R = cv2.getRotationMatrix2D((mirror.shape[1] / 2, mirror.shape[0] / 2), r, 1)
        mirror = cv2.warpAffine(mirror, R, (mirror.shape[1], mirror.shape[0]))
        mirror = mirror[top:bottom, left:right]

        return mirror

    def align(self, img):
        mirror = self.padding(img)
        detected = self.detect(img, mirror)
        return detected


def main(args):
    mp = MirrorPadding('shape_predictor_68_face_landmarks.dat')

    paths = glob.glob(os.path.join(args.input_dir, '*'))
    for i, path in enumerate(paths):
        dst = os.path.join(args.output_dir, os.path.basename(path))
        if os.path.exists(dst):
            continue
        img = cv2.imread(path)
        detected = mp.align(img)
        if detected is None:
            print('Not detected: {}'.format(path))
            continue
        if min(detected.shape[:2]) < args.image_size:
            print('Too small: {}'.format(path))
            continue

        scaled = cv2.resize(detected, (args.image_size, args.image_size),
                            interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(dst, scaled)
        print('{}/{} - {}'.format(i+1, len(paths), path))
        
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input_dir', required=True)
    parser.add_argument('--output_dir', required=True)
    parser.add_argument('--image_size', type=int, default=1024)
    parser.add_argument('--gpu', type=str)
    if parser.parse_args().gpu:
        os.environ['CUDA_VISIBLE_DEVICES'] = parser.parse_args().gpu
    main(parser.parse_args())
