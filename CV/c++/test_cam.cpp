#include <opencv2/opencv.hpp>
#include <iostream>

using namespace cv;
using namespace std;

int main() {
    VideoCapture cap(0, CAP_V4L2);
    if (!cap.isOpened()) {
        cerr << "Cannot open camera" << endl;
        return -1;
    }

    cap.set(CAP_PROP_FRAME_WIDTH, 640);
    cap.set(CAP_PROP_FRAME_HEIGHT, 480);

    Mat frame;
    while(true){
        cap >> frame;
        if(frame.empty()) break;

        imshow("Pi Camera Test", frame);

        if(waitKey(1) == 'q') break;
    }
}
