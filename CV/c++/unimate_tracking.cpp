#include <opencv2/opencv.hpp>
#include <opencv2/dnn.hpp>
#include <iostream>
#include <unistd.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <sys/ioctl.h>

using namespace std;
using namespace cv;

// ===========================================
//     PCA9685 DRIVER CLASS (C++) - FIXED
// ===========================================
class PCA9685 {
private:
    int fd;
    int addr = 0x40;

    // Write byte to register
    void writeReg(unsigned char reg, unsigned char data) {
        uint8_t buf[2] = { reg, data };
        if (write(fd, buf, 2) != 2) {
            cerr << "Failed to write to I2C\n";
        }
    }

    // Read byte from register
    unsigned char readReg(unsigned char reg) {
        if (write(fd, &reg, 1) != 1) {
            cerr << "Failed to write register address\n";
            return 0;
        }
        uint8_t val;
        if (read(fd, &val, 1) != 1) {
            cerr << "Failed to read from I2C\n";
            return 0;
        }
        return val;
    }

public:
    PCA9685(int bus = 1) {
        char filename[20];
        sprintf(filename, "/dev/i2c-%d", bus);

        fd = open(filename, O_RDWR);
        if (fd < 0) {
            cerr << "Failed to open I2C bus\n";
            exit(1);
        }

        if (ioctl(fd, I2C_SLAVE, addr) < 0) {
            cerr << "Could not set I2C slave\n";
            exit(1);
        }

        // Reset PCA9685
        writeReg(0x00, 0x00);
        setPWMFreq(50);
    }

    void setPWMFreq(int freq) {
        float prescaleval = 25000000.0;
        prescaleval /= 4096.0;
        prescaleval /= freq;
        prescaleval -= 1.0;

        unsigned char prescale = floor(prescaleval + 0.5);

        unsigned char oldmode = readReg(0x00);
        unsigned char newmode = (oldmode & 0x7F) | 0x10;
        writeReg(0x00, newmode);
        writeReg(0xFE, prescale);
        writeReg(0x00, oldmode);
        usleep(5000);
        writeReg(0x00, oldmode | 0xa1);
    }

    void setPWM(int channel, int on, int off) {
        writeReg(0x06 + 4 * channel, on & 0xFF);
        writeReg(0x07 + 4 * channel, on >> 8);
        writeReg(0x08 + 4 * channel, off & 0xFF);
        writeReg(0x09 + 4 * channel, off >> 8);
    }

    void setServoAngle(int channel, float angle) {
        int pulse = int(150 + (angle / 180.0) * 450);
        setPWM(channel, 0, pulse);
    }
};

// ===========================================
//           EMOTION MODEL LABELS
// ===========================================
vector<string> emotions = {
    "Angry", "Disgust", "Fear", "Happy",
    "Sad", "Surprise", "Neutral"
};

// ===========================================
//               MAIN PROGRAM
// ===========================================
int main() {
    // ------------------------ CAMERA & MODELS ------------------------
    CascadeClassifier faceCascade;
    if (!faceCascade.load("haarcascade_frontalface_default.xml")) {
        cerr << "Failed to load Haar Cascade\n";
        return -1;
    }

    dnn::Net emotionNet = dnn::readNetFromONNX("emotion-ferplus-8.onnx");
    emotionNet.setPreferableBackend(dnn::DNN_BACKEND_OPENCV);
    emotionNet.setPreferableTarget(dnn::DNN_TARGET_CPU);

    VideoCapture cap(0);
    if (!cap.isOpened()) {
        cerr << "Camera not detected!" << endl;
        return -1;
    }

    // ------------------------ SERVO SETUP ------------------------
    PCA9685 pwm;

    int base_ch = 0;      // Left-right
    int head_ch = 1;      // Up-down
    int stand_ch = 2;     // Big rotation base

    float base_angle = 110;
    float head_angle = 90;
    float stand_angle = 90;

    pwm.setServoAngle(base_ch, base_angle);
    pwm.setServoAngle(head_ch, head_angle);
    pwm.setServoAngle(stand_ch, stand_angle);

    // Movement constants
    float SMOOTH = 0.05;
    float MAX_STEP = 3;
    int STAND_THRESHOLD = 80;

    // ------------------------ LOOP ------------------------
    while (true) {
        Mat frame;
        cap >> frame;
        if (frame.empty()) break;

        Mat gray;
        cvtColor(frame, gray, COLOR_BGR2GRAY);

        vector<Rect> faces;
        faceCascade.detectMultiScale(gray, faces, 1.2, 5);

        int frame_w = frame.cols;
        int frame_h = frame.rows;
        int cx = frame_w / 2;
        int cy = frame_h / 2;

        for (auto &face : faces) {
            rectangle(frame, face, Scalar(0, 255, 0), 2);

            // Face center
            int fx = face.x + face.width / 2;
            int fy = face.y + face.height / 2;

            int dx = fx - cx;
            int dy = fy - cy;

            // ------------------------ STAND SERVO (big moves) ------------------------
            if (abs(dx) > STAND_THRESHOLD) {
                if (dx > 0) stand_angle -= 3; else stand_angle += 3;
                stand_angle = max(45.0f, min(135.0f, stand_angle));
                pwm.setServoAngle(stand_ch, stand_angle);
            }

            // ------------------------ BASE & HEAD ------------------------
            float t_base = base_angle - dx * SMOOTH;
            float t_head = head_angle + dy * SMOOTH;

            t_base = max(45.0f, min(135.0f, t_base));
            t_head = max(50.0f, min(180.0f, t_head));

            float db = max(-MAX_STEP, min(MAX_STEP, t_base - base_angle));
            float dh = max(-MAX_STEP, min(MAX_STEP, t_head - head_angle));

            base_angle += db;
            head_angle += dh;

            pwm.setServoAngle(base_ch, base_angle);
            pwm.setServoAngle(head_ch, head_angle);

            // ------------------------ EMOTION DETECTION ------------------------
            Mat faceROI = gray(face);
            resize(faceROI, faceROI, Size(64, 64));
            faceROI.convertTo(faceROI, CV_32F, 1.0 / 255.0);

            Mat blob = dnn::blobFromImage(faceROI, 1.0, Size(64, 64), Scalar(0), true, false);
            emotionNet.setInput(blob);

            Mat out = emotionNet.forward();

            Point classId;
            double conf;
            minMaxLoc(out, 0, &conf, 0, &classId);

            string emotion = emotions[classId.x];

            putText(frame, emotion, {face.x, face.y - 10},
                    FONT_HERSHEY_SIMPLEX, 0.7, Scalar(0, 255, 255), 2);

            break; // only track first face
        }

        imshow("UniMate Tracking", frame);
        if (waitKey(1) == 'q') break;
    }

    return 0;
}