const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

async function convertSvgaToPng(svgaFilePath, outputDir) {
    const absoluteSvgaPath = path.resolve(svgaFilePath);
    const absoluteOutputDir = path.resolve(outputDir);

    if (!fs.existsSync(absoluteOutputDir)) {
        fs.mkdirSync(absoluteOutputDir, { recursive: true });
    }

    // 1. 读取文件并转为 Base64
    const svgaBuffer = fs.readFileSync(absoluteSvgaPath);
    const svgaBase64 = svgaBuffer.toString('base64');

    console.log('Launching browser...');
    const browser = await puppeteer.launch({
        headless: 'new',
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    const page = await browser.newPage();

    // 2. 修改后的 HTML 内容：增加 Blob URL 转换逻辑
    const htmlContent = `
        <!DOCTYPE html>
        <html>
        <head>
            <title>SVGA Renderer</title>
            <script src="https://cdn.jsdelivr.net/npm/svgaplayerweb@2.3.1/build/svga.min.js"></script>
        </head>
        <body style="margin:0; background:transparent;">
            <canvas id="canvas"></canvas>
            <script>
                window.loadSvga = async (base64Data) => {
                    const canvas = document.getElementById('canvas');
                    try {
                        const parser = new SVGA.Parser(canvas); 
                        const player = new SVGA.Player(canvas);

                        // --- 关键修复开始 ---
                        // 1. 将 Base64 转换为二进制数据
                        const binaryString = atob(base64Data);
                        const len = binaryString.length;
                        const bytes = new Uint8Array(len);
                        for (let i = 0; i < len; i++) {
                            bytes[i] = binaryString.charCodeAt(i);
                        }

                        // 2. 创建 Blob 对象
                        const blob = new Blob([bytes.buffer], { type: 'application/octet-stream' });
                        
                        // 3. 创建 Blob URL (这是解析器能够识别的有效 URL)
                        const blobUrl = URL.createObjectURL(blob);
                        
                        // 4. 使用 Blob URL 加载
                        await new Promise((resolve, reject) => {
                            parser.load(blobUrl, (videoItem) => {
                                player.setVideoItem(videoItem);
                                canvas.width = videoItem.videoSize.width;
                                canvas.height = videoItem.videoSize.height;
                                
                                window.videoItem = videoItem;
                                window.player = player;
                                resolve();
                            }, (error) => {
                                console.error('SVGA Parse Error:', error);
                                reject(error);
                            });
                        });
                        // --- 关键修复结束 ---

                        return { success: true, frames: window.videoItem.frames, width: canvas.width, height: canvas.height };
                    } catch (e) {
                        console.error(e);
                        return { success: false, error: e.message };
                    }
                };

                window.captureFrame = (frameIndex) => {
                    window.player.stepToFrame(frameIndex);
                    const canvas = document.getElementById('canvas');
                    return canvas.toDataURL('image/png');
                };
            </script>
        </body>
        </html>
    `;

    await page.setContent(htmlContent);

    console.log('Loading SVGA file...');
    
    const meta = await page.evaluate((b64) => {
        return window.loadSvga(b64);
    }, svgaBase64);

    if (!meta.success) {
        console.error('Failed to load SVGA:', meta.error);
        await browser.close();
        return;
    }

    console.log(`Video Info: ${meta.width}x${meta.height}, Total Frames: ${meta.frames}`);

    // 3. 遍历帧并保存
    for (let i = 0; i < meta.frames; i++) {
        const dataUrl = await page.evaluate((frame) => {
            return window.captureFrame(frame);
        }, i);

        const base64Data = dataUrl.replace(/^data:image\/png;base64,/, "");
        const buffer = Buffer.from(base64Data, 'base64');
        
        const fileName = `${String(i).padStart(4, '0')}.png`;
        const filePath = path.join(absoluteOutputDir, fileName);
        
        fs.writeFileSync(filePath, buffer);
        
        if (i % 10 === 0) {
            console.log(`Processing frame ${i}/${meta.frames}`);
        }
    }

    console.log(`\nDone! Frames saved to: ${absoluteOutputDir}`);
    await browser.close();
}

// 运行
const args = process.argv.slice(2);
if (args.length < 2) {
    console.log("Usage: node convert.js <input.svga> <output_folder>");
} else {
    convertSvgaToPng(args[0], args[1]).catch(console.error);
}
