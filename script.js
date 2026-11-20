
async function loadImage() {
    try {
        const response = await fetch(
            `current_image.json?t=${Date.now()}`
        );

        if (!response.ok) {
            throw new Error("Image data unavailable");
        }

        const data = await response.json();

        const image = document.getElementById("christmas-image");
        const credit = document.getElementById("image-credit");

        image.src = data.image_url;
        image.alt = data.description || "Christmas image";

        credit.textContent = data.author
            ? `Photo: ${data.author}`
            : "Christmas inspiration";
    } catch (error) {
        console.error(error);
        document.getElementById("image-credit").textContent =
            "Christmas magic is coming...";
    }
}

loadImage();

// Check for a new image every minute
setInterval(loadImage, 60 * 1000);
